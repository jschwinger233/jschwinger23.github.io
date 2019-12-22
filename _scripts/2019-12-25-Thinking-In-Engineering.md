---
layout: post
---

2015 年 12 月 18 日周五, 我在北京找到了第一份程序员工作, 一蹦一跳从望京出来.

2016 年的生日, 我在空间里写下 "我非常害怕，四年后的我，在数据库底层、操作系统底层，HTTP 协议、并发、分布式系统都没有深入地理解，掌握着一门或者几门脚本语言却 BUG 辈出。"

转眼就是四年后了, 我走了一万一千里路站在这里, 总算培养出一些评判代码好坏的纲领, 索性记录一下当前对工程的思考.

# 1. 并发细节

并发这个主题早在 2018 年 6 月乘坐悉尼到 New Castle 的火车时就思绪万千了, 当时读着都能背诵下来的 Python Cookbook 第 13 章, 心里想着各种各样的话题: 惊群, 自旋锁, self-pipe trick...

## 1.1 Context

奇怪的是只有 Go 才把 Context 作为核心抽象, 而其他语言(Python, Rust)要实现类似的功能都很扭曲, 以至于有时候你已经实现了一个 Context 但你自己都没意识到这就是 Context.

先跳出来思考, 在没有 Context 的世界一般我们是如何中断一个正在运行的线程/协程(以下简称`*程`)的:

1. 通过变量在旁路控制

也就是说消费者在取消息前都先判断一个布尔变量 `running`, 若为 false 则不再消费. 注意由于设置变量不具备通知能力, 所以可能要在取消息前后都要检查一次变量:

```python
class Dispatcher:
    def run(self):
        while self.running:
            try:
                msg = self.queue.get(timeout=1)
            except Timeout:
                continue
            if not self.running:
                return
```

2. 通过 IO 多路复用在旁路控制

这个做法能解决的问题是可以在 IO 阻塞处中断(如上面的 `queue.get(timeout=1)`), 所利用的技术是 self-pipe trick, 伪代码是这样的:

```python
def run():
    while True:
        readable, _, _ = select([queue, pipe], [], [])
        if pipe in readable:
            return
        if queue in readable:
            msg = queue.get()
```

我们会发现这本质上和 Go 的 Context 用法是一样的.

严格来说, 我们必须对一切操作 channel 的地方同时处理 context, 比如说迭代操作 `for v := range ch {}` 理论上应该写做:

```go
loop:
for {
    select {
    case <- ctx.Done();
        break loop
    case maybeV, ok := <- ch:
        if !ok {
            return
        }
    }
}
```

但是实际上这么写太神经病了, 重点是掌握思想, 这里的本质思想是对*程生命周期的控制, 然后具体的情况具体实施.

思考题: 实现线程版本的 `gevent.Timeout`:

```python
try:
    with timeout(1):
        do()
except Timeout:
    pass
```

## 1.2 fan-out, fan-in

我们要做大量的 etcd get, 想用 etcd bulky get 来提升性能, 然而 etcd bulky get 一个请求只能携带... 忘了多少个 key 了, 假设 150 个吧, 因此我们要用多个*程发 bulky get 最后把结果收回来.

这件事情在 Python 里特简单, 直接 `concurrent.futures` 一波带走:

```python
with ThreadPoolExecutor(max_works=10) as executor:
    future = executor.submit(batch_get, keys)
    futures.append(futures)

for future in futures:
    res.extend(future.result())
```

但是用 Go 来做的话, 如果让小朋友来写的话第一次不是不知所措就是死锁.

这里有好几种思路, 但是最成熟的做法应该是用 fan-out fan-in pattern:

```go
gw := GroupWait(10)
for _ := range 10 {
    go func() {
        defer gw.Done()
        ch <- batch_get(keys)
    }
}

go func(){
    defer close(ch)
    gw.Wait()
}
```

由于 Go 对 channel 的限制是只能 close 一次否则 panic, 同时 close 是广播通知, 因此一般情况下把 channel 视为单生产多消费(spmc)就没错了; 在真的需要 mpmc 的时候一定要用 fan-in fan-out 模式来做同步.

思考题: 在 Gevent 解决这个问题的时候可以直接用 Pool 抽象很方便地解决:

```python
for _ in range(10);
    pool.spawn(batch_get, keys)
pool.wait()
```

那么在 Go 里面对应的 Pool 抽象是什么?


## 1.3 leak

协程泄漏是在 Go 流行后才引起大家重视, 然而在线程场景下依然非常常见.

先看一个常见的泄漏, 用 Go 实现一个 `Timeout(time.Duration, func() error)`:

```go
func WithTimeout(timeout time.Duration, f func() error) error {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	var err error
	data := make(chan error)
	go func() {
		data <- f()
	}()
	select {
	case <- ctx.Done():
		return types.ErrTimeout
	case err := <- data:
		return err
	}
}
```

这里的泄漏非常典型, 在 `f()` 超时的情况下, `select` 会退出导致没有消费者消费 `data` channel, 这样当 `f()` 最终返回时, `go func() { data <- f() }` 这个协程会永远阻塞在 `data <-` 上从而无法释放, 导致泄漏.

网上的垃圾博客会教大家在只要创建 channel 时预留缓冲区就可以了: `data := make(chan error, 1)`, 当然这可以解决问题, 但是更好的做法应该是利用 context:

```python
go func() {
    select {
    case data <- f(): return
    case <-ctx.Done(): return
    }
}
```

这样的话一旦超时协程立刻会退出.

不过这样还是不够好, 这样依然会导致 `f()` 的运行, 最好的做法传入 context 到 `f()` 里, 从而对协程进行打断和控制; 这里我再次强调对协程生命周期的控制这一重要思想.

而线程泄漏则是大家在过去很容易忽略的地方, 来看这个例子:

```python
def race_fetch(n):
    def f(q):
        q.put(fetch())

    q = Queue()
    for _ in range(n):
        Thread(target=f, args=(q,)).start()
    return q.get()
```

类似的情况, 当返回第一个结果后, 其他的线程将阻塞在 `q.put()`.

# 2. 工程细节

工程细节是指构成一份工业级代码的必要细节, 没有这些细节的代码仓库一概被我称为**.

## 2.1 graceful termination

graceful termination 已经在我过去已经多次提及了, 基本语义是"不再接收请求并等待现有请求处理完毕".

常规做法是:

1. 设置全局结束 flag, 在收到信号时 toggle.
2. 不再接收请求; 对于服务器而言就是不再 accept, 对 daemon 而言就是不再接收事件
3. 等待正在处理的请求结束, 一般做法是让所有新请求从并发池里获取, 那么这时候直接等待并发池为空就可以了.

照抄 Gunicorn 的代码:

```python
for server in servers:
    server.close()

# Handle current requests until graceful_timeout
ts = time.time()
while time.time() - ts <= self.cfg.graceful_timeout:
    accepting = 0
    for server in servers:
        if server.pool.free_count() != server.pool.size:
            accepting += 1

    # if no server is accepting a connection, we can exit
    if not accepting:
        return

    self.notify()
    gevent.sleep(1.0)

# Force kill all active the handlers
for server in servers:
    server.stop(timeout=1)
```

gunicorn 的实现是连接池对应并发池, 因此数连接数就可以了; 不过正因为没有并发池的抽象, 导致没有一个集成到事件循环的 wait 方法, 只能 sleep, 很菜的样子.

看看 Go 的做法, 照抄 grpc-server:

```go
s.mu.Lock()
for lis := range s.lis {
    lis.Close()
}
s.lis = nil

// Wait for serving threads to be ready to exit.  Only then can we be sure no
// new conns will be created.
s.mu.Unlock()
s.serveWG.Wait()
s.mu.Lock()

for len(s.conns) != 0 {
    s.cv.Wait()
}
s.conns = nil

if s.events != nil {
    s.events.Finish()
    s.events = nil
}
s.mu.Unlock()
```

看下来就是三件套: 停止新请求, 等待 `serveWG` (counts active Serve goroutines), 清理其他变量(`events` 是容器事件日志, `cv` 是连接关闭广播).

只要项目架构合理, 做起来并不复杂.

不过一旦项目架构不合理, 那要做的事情可就多了去了.

# 2.2 Connection Pool

连接池向来是企业级 library 必备模块, 但是我见过太多垃圾透顶的实现了.

先说一个工业级别的连接池应该有哪些功能:

服务端连接池:

客户端连接池:
1. pool size: 容量;
2. ttl: 超时关闭;
3. cycle interval: 清理 idle 的间隔时间;
4. get connection 和 release connection 必须线程安全;
5. `CLOSE_WAIT` 的正确处理: idle 连接可能被服务端关闭, 应用必须及时处理 FINed 半关闭连接;

此外有个二选一项目:
1. get connection timeout: 取连接池的等待超时;
2. 或者让 pool size 定义为 idle 容量, 可以任意 get connection, 但是用完后最多保持 pool size 个 idle 连接;

做一些说明:

1. pool size 作为 idle 容量且可以任意 get connection 是 Nginx 的 upstream connection pool 行为;
2. 作为客户端的连接池 ttl 是必要的, 不仅是因为及时释放服务端的 fd, 也可以规避 NAT 定时器的问题;

然而我见过大部分玩家连个线程安全都做得稀烂, 更别说 `CLOSE_WAIT` 的处理了.

来看一个最简单的实现, 连 size 都没有的那种:

```python
class ConnectionPool:
    def __init__(self):
        self._available_connections = []
        self._in_use_connections = set()

    def get(self):
        while True:
            try:
                connection = self._available_connections.pop()
                self.validate(connection)
                break
            except IndexError:
                connection = self.make_connection()
                break
            except OSError:
                with suppress(Exception):
                    connection.close()

        self._in_use_connections.add(connection)
        return connection

    def release(self, connection):
        self._in_use_connections.remove(connection)
        self._available_connections.append(connection)
```

和很多人预料的不同, 这段代码是正儿八经地线程安全, 因为 CPython 的实现里 list.append / list.pop 和 set.add / set.remove 都是原子的, 因此完全没有必要写大段的性能低下的互斥锁.

其次, 由于采用 FIFO (list)存储可复用的连接, 可能会导致大量的 `CLOSE_WAIT` 的连接积压在栈的底部造成严重的连接泄漏; 要解决这个问题甚至可以简单把栈换成 FILO (like deque)就可以了.

作为一个自用的小项目这个 pool 可以说是基本够用了, 只要把数据结构改成 deque, 但是作为工业级连接池还应该实现一个计时器每秒(cycle interval)检查连接的 idle time, 超过 ttl 就清理; 如果超过 pool size 就从老到新清理 idle; 最好对 `CLOSE_WAIT` 也进行周期检查.

这个小组件可以说是能够对工程师的工程能力以小见大地进行判断, 希望大家多思考, 多写出工业级别的代码.

# 2.3 FSM


## 3. Architecture

认识太多

# 3.1 layer

# 2.2 HTTP API (REST)

我当然不是说 RESTful API 是最吼的, 但是它所反映的思想是清晰的, 是有适用的场景的.
