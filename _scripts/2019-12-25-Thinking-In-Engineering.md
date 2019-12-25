---
layout: post
---

2015 年 12 月 18 日周五, 我在北京找到了第一份程序员工作, 一蹦一跳从望京出来.

转眼就是四年后了, 我走了一万一千里路站在这里, 总算培养出一些评判代码好坏的纲领, 索性记录一下当前对工程的思考, 也算是对这四年的总结.

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

## 1.2 Fan-out, Fan-in

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


## 1.3 Leak

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

一些我认为很重要, 却不怎么见到别人提到, 但在工作中常被其他人写得一塌糊涂的工程小问题.

## 2.1 Graceful Termination

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

## 2.2 Connection Pool

连接池向来是企业级 library 必备模块, 但是我见过太多垃圾透顶的实现了.

先说一个工业级别的连接池应该有哪些功能:

1. pool size: 容量;
2. ttl: 超时关闭;
3. cycle interval: 清理 idle 的间隔时间;
4. race condition: get connection 和 release connection 必须线程安全;
5. `CLOSE_WAIT`: idle 连接可能被服务端关闭, 应用必须及时处理 FINed 半关闭连接;

此外有个二选一项目:
1. get connection timeout: 取连接池的等待超时;
2. 或者让 pool size 定义为 idle 容量, 可以任意 get connection, 但是用完后最多保持 pool size 个 idle 连接; 在这种情况下需要再多一个参数:
3. inactivity time, 超过 inactivity time 的 idle 连接才会为了保持 pool size 而清理;

做一些说明:

1. pool size 作为 idle 容量且可以任意 get connection 是 Nginx 的 upstream connection pool 行为, 我觉得作为软限制是很好的设计;
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

## 2.3 FSM

Finite-state machine 有限状态机, 别说用不到, 我随手举出一些工程上的例子:

1. TCP 套接字状态变化
2. 异步任务的状态跟踪
3. 监控分布式服务的状态
4. 容器/进程生命周期的管理
5. ~~正则表达式匹配 3 的倍数~~

采用状态机思考的最大好处是状态变化一目了然, 在绘制状态转换图和状态表的时候可以轻易发现逻辑 bug, 同时非常有利于编程建模.

比放说中央已经决定了使用 state pattern 去实现 FSM, 来看一个简单的例子(直接从 Rust Book ch17-03 抄袭的), 博客发布需要经历的状态:

![post FSM](https://github.com/jschwinger23/jschwinger23.github.io/blob/master/data/fsm.png?raw=true)

假如用 state pattern 去做的话大概是这样的:

```go
type PostState interface {
    Cancel() (PostState, error)
    Review() (PostState, error)
    Approve() (PostState, error)
    Modify() (PostState, error)
    Content() (string, error)
}

type Draft struct {
    buf string
}

func (d *Draft) Cancel() (PostState, error) {
    return d, nil
}

func (d *Draft) Review() (PostState, error) {
    return NewPreview(d.buf), nil
}

func (d *Draft) Approve() (PostState, error) {
    return nil, ErrInvalidAction
}
```

之类的一大堆乏味的代码, 最后的调用是:

```go
type Post struct {
    state PostState
}

func (p *Post) Review() (err error) {
    p.state, err = p.state.Review()
    return
}

func (p *Post) Approve() (err error) {
    p.state, err = p.state.Approve()
    return
}
```

之类的又是一大堆乏味的代码.

从这里就可以看到 state pattern 实现状态机最饱受批判的地方: 必须对所有状态实现所有方法, 同时这样也造成了扩展性的问题: 假如之后在某状态新增了新动作, 则不得不在所有状态都实现一遍, 即使对大部分状态都无意义, 而且这也破坏了开放封闭原则.

有些时候反模式也许是不错的, 比方说:

```go
type DraftPost struct {
    buf string
}

func (d *DraftPost) Review() PreviewPost {
    return NewPreviewPost(d.buf)
}

type PreviewPost struct {}

func (p *Preview) ApprovePost() PublishedPost {}
```

不过这样的话外部调用必须跟踪每一步骤返回值:

```go
preview := draft.Review()
published := preview.Approve()
content := published.Content()
```

而不能像之前始终是一个动作:

```go
err = post.Review()
err = post.Approve()
content, err := post.Content()
```

这是用和不用 state pattern 的 trade-offs.

~~话说回来, 在古代 Python 里有一招可以 runtime 切换实例的 `__class__` 从而改变类型, 的 FSM 实现方式, 虽然大家都说不好, 但其实我觉得还挺带感, 尤其旧类还比新类快都不知道哪里去了(~~

专门提到 FSM 是因为它其实远比大部分人想象得更常见, 但是大部分人又在本该用 FSM 去思考的时候沉迷于 if-else / switch-case 而错过了优雅的建模方式, 殊不知复杂业务的工程建模正是编程里最有趣最有挑战的部分之一.

# 3. Project Design

且不说架构, 只论单项目的设计, 毫不夸张地说, 大部分工作两年的工程师做出来的东西就是一堆屎山.

## 3.1 Layer

分层理论可不是傻叉的 MVC, MVC 的每一层和其他层深度耦合, 呈现一个三角依赖关系, 假设我们要新增一个服务协议 GRPC,  用 MVC 都没法开放封闭, 基本就是一个垃圾.

来看经典分层理论:

![layer](https://github.com/jschwinger23/jschwinger23.github.io/blob/master/data/layer.png?raw=true)

0. **分层架构的基本原则**

* ~~上层只与下层耦合; 严格分层架构要求上层只能和相邻的下层耦合, 松散分层架构允许上层同任意下层耦合.~~这是古典分层理论, 下面的现代理论取代了这一条.
* 依赖倒置: 上层不依赖下层, 它们都只依赖抽象; 抽象不依赖实现, 实现依赖抽象.

1. **Presentation Layer**

Presentation 层处理安全, 协议, 对外数据展示.

Presentation 与下层的区别是这一层连模型(Model)都接触不到, 传入给下层与从下层获得的数据都是 primitive type.

2. **Application Layer**

App 层处理事务, 安全和事件, 由这一层驱动保证一致性.

App 层与下层的区别是这一层不处理业务逻辑, 只作为业务逻辑层的客户端调用服务接口, 也能是直接调用模型的方法, 也可能是调用业务服务, 是很轻量的一层.

3. **Business Layer**

Business 层是建模与实际业务所在的层, 是最重最复杂的层.

Business 层与下层的区别是这一层不关心基础设施细节, 缓存, 持久化 ...

4. **Infrastructure Layer**

Infra 层实现所需要的基础设施, 数据库, 队列, 分布式存储...

Infra 层与上层的区别是这一层不关心业务逻辑, 但是关心业务模型.

---

来看一个简单的例子(直接从 Alistair Cockburn 的 [hexagonal architecture](https://web.archive.org/web/20180822100852/alistair.cockburn.us/Hexagonal+architecture) 照抄..)

提供一个简单的服务, 输入产品 ID 和 amount, 返回总价格, 折扣率随 amount 变化, 从数据库查取.

### Presention Layer

假设这个服务接受两种协议的请求: GRPC 和 HTTP, 那么表现层将负责这两种协议的翻译:

先在表现层定义下层的接口:

```go
// presentation/interface.go
type Application interface {
    CalculateCost(productID int, amount int) (float64, error)
}
```

然后分别实现两种协议:

HTTP:

```go
// presentation/http/server.go
type HTTPServer {
    App Application
}

func (s *HTTPServer) ServeHTTP() {
    http.HandleFunc("/cost", func(w http.ResponseWriter, req *http.Request) {
        amount, err := strconv.Atoi(req.FromValue("amount"))
        productID, err := strconv.ParseFloat(req.FromValue("product_id"))
        cost, err := s.App.CalculateCost(productID, amount)
        fmt.Fprintf(w, "{"cost": %f}", cost)
    })
}
```

GRPC:

```go
// presentation/grpc/server.go
type GRPCServer {
    App Applicaiton
}

func (s *GRPCServer) ServerGRPC {
    server := grpc.NewServer()
    pb.RegisterServer(server, s)
    err := server.Serve()
}

func (s *GRPCServer) CalculateCost(ctx context.Context, req *pb.CalculateCostRequest) (*pb.CostReply, error) {
    return &pb.CostReply{Cost: s.App.Calculate(req.ProductID, req.Amount)}, nil
}
```

HTTPServer 与 GRPCServer 里的 App 是在 main 函数里依赖注入的(DI).

### Application Layer

应用层讲道理应该从表现层导入接口, 然而由于 Go 独特的接口设计导致不需要 import, 所以看不出`依赖倒置`, 在其他语言里 (Rust / Java) 则会看到`下层 import 上层` 这一重要特征.

老规矩, 先定义下层接口:

```go
// application/interface.go
type Repo interface {
    GetProduct(int) (Product, error)
}

type Product interface {
    CalculateCost(amount int) (float64, error)
}
```

```go
// application/app.go
type App {
    Repo
}

func (a *App) CalculateCost(productID int, amount int) (float64, error) {
    product, err := a.Repo.GetProduct(id)
    return product.CalculateCost(amount)
}
```

我们发现应用层定义了基础层和业务层的两个接口, 在松散分层架构时这是很正常的.

### Business Layer

再次提醒依赖倒置原则和依赖注入在每一层的实现, 只是因为 Go 实现接口不需要导入接口定义所以没有反映出来.

```go
// business/interface.go
type Repo interface {
    GetDiscountRate(productID int, amount int) (float64, error)
}
```

```go
// business/model.go
type Product {
    price   float64
    ID      int
    Repo
}

func (p Product) CalculateCost(amount int) (float64, error) {
    rate, err := p.Repo.GetDiscountRate(p.ID, amount)
    return rate * p.price * amount, err
}
```

### Infra Layer

基础层只要分别实现在应用层和业务层定义的接口就可以了:

```go
// infra/repo.go
type Repo struct {}

func (r *Repo) GetProduct(productID int) (Product, error) {
    ...
}

func (r *Repo) GetDiscountRate(productID int, amount int) (float64, error) {
    ...
}
```

## 2.2 HTTP API (REST)

我当然不是说 RESTful API 是最吼的, 但是它所反映的思想是清晰的, 是有适用的场景的.
