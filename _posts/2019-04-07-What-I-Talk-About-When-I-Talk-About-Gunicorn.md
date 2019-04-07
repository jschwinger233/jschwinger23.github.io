---
layout: post
---

> 誰摘下王冠，誰發現寶藏。by 吴青峰

WSGI 发布以来, Gunicorn 逐渐成为 Python Web 部署的标准套件之一, 让我们先简单复习下它的主要工作:

1. web server (like NGINX) 与 Python application (like Django) 的沟通桥梁
    1. 与 web server 通过 socket 通信
    2. 与 application 通过 WSGI 通信
2. 子进程管理
    0. daemon 相关
    1. 保活心跳
    2. 维持指定 worker 数量
    2. 信号管理
        1. `SIGHUP` reloads 配置
        2. `SIGTTOU` 增加一个 worker 进程
        3. `SIGTTIN` 减少一个 worker 进程
        4. `SIGTERM` 优雅退出
3. 配置管理
    1. 并发模式: Gevent / Thread / Sync / Tornado
    2. 定期重启避免内存泄露
    3. 并发数量
    4. keepalive 数量

毫无疑问, 这个一个优秀的工业产品, 被大规模应用在生产环境, 经过了岁月的洗礼; 但是, 它不够杰出.

### 1. 公审: Gunicorn

先看 Gunicorn 里 master 进程的[主循环](https://github.com/benoitc/gunicorn/blob/19.9.0/gunicorn/arbiter.py#L197-L241):

```python
while True:
    self.maybe_promote_master()

    sig = self.SIG_QUEUE.pop(0) if self.SIG_QUEUE else None
    if sig is None:
        self.sleep()
        self.murder_workers()
        self.manage_workers()
        continue

    if sig not in self.SIG_NAMES:
        self.log.info("Ignoring unknown signal: %s", sig)
        continue

    signame = self.SIG_NAMES.get(sig)
    handler = getattr(self, "handle_%s" % signame, None)
    if not handler:
        self.log.error("Unhandled signal: %s", signame)
        continue
    self.log.info("Handling signal: %s", signame)
    handler()
    self.wakeup()
```

看起来还是好理解的, 我们挑主要逻辑看:

1. `SIG_QUEUE` 是收到了待办信号队列, 信号 handler 仅仅是把信号塞入队列而不是直接处理, 这样的好处是不会打断一个正在运行的流程. I mean, 这样只会打断一下, 塞队列, 然后结束信号处理, 但是不会执行一个漫长的操作. 让信号处理尽量短小是 Unix 程序员的基本素养, 否则异步信号安全分分钟教你做人.
2. 如果当前 `SIG_QUEUE` 没有待办信号, 那就睡一段时间.
    2. 睡醒了 `murder_workers` 处理心跳超时的 worker.
    3. 接着 `manage_workers` 补充 worker 数量.
3. 如果当前 `SIG_QUEUE` 有待办信号, 则不维护 worker 进程, 而是回调真正的信号处理器.
4. 无限循环.

好了我要开始批判了.

#### 1.1. `self.wakeup`

最后的那个 `self.wakeup` 是什么鬼?

好, 你去看了代码, 嗷, 原来是因为为了不让 `self.sleep()` 的时候错过了需要及时处理的信号, 睡眠是通过阻塞在 `select.select()` 实现的, 而收到信号后会写一字节到一个 pipe, 从而唤醒 `select.select()` 的阻塞.

嗯, 很经典的 [self-pipe trick](http://man7.org/tlpi/code/online/diff/altio/self_pipe.c.html), 它本质要解决的问题是同时等待信号和文件描述符, Linux 在 2.6.16 之后有 `pselect(2)` / `ppoll(2)` / `epoll_pwait(2)`, 2.6.27 之后有 `signalfd`, 不过两者都不属于 SUSv3, 所以 Gunicorn 作为一个跨平台的轮子, 采用了古典的 self-pipe trick.

那么最后一个 `self.wakeup()` 是什么目的呢? 是因为处理完信号之后, 希望能够立刻处理搁置了一段时间的 `self.murder_workers` 和 `self.manage_workers`, 就不要再睡觉了, 因此 `self.wakeup` 往 pipe 里写一字节数据, 之后的 `self.sleep` 就会立刻被唤醒.

好像没啥问题, 甚至可以夸赞一句非常缜密的处理逻辑.

但是问题是, 这种看顶层 API 却完全不知道是干嘛的代码, 是典型的抽象不到位, 导致实现细节侵入到业务逻辑, 就好比是在 MVC 架构里的 view function 里调用了一个数据库保活的函数, which 本应该在 ORM 之下的连接池里实现, 都是行为艺术.

这里只是 Gunicorn 抽象混乱的冰山一角.

#### 1.2. 抽象

比方说上面出现的 `manage_workers` 的[实现](https://github.com/benoitc/gunicorn/blob/19.9.0/gunicorn/arbiter.py#L539):

```python
def manage_workers(self):
    """\
    Maintain the number of workers by spawning or killing
    as required.
    """
    if len(self.WORKERS.keys()) < self.num_workers:
        self.spawn_workers()

    workers = self.WORKERS.items()
    workers = sorted(workers, key=lambda w: w[1].age)
    while len(workers) > self.num_workers:
        (pid, _) = workers.pop(0)
        self.kill_worker(pid, signal.SIGTERM)

    active_worker_count = len(workers)
    if self._last_logged_active_worker_count != active_worker_count:
        self._last_logged_active_worker_count = active_worker_count
        self.log.debug("{0} workers".format(active_worker_count),
                       extra={"metric": "gunicorn.workers",
                              "value": active_worker_count,
                              "mtype": "gauge"})
```

平铺直叙的逻辑, 能理解, 经得起推敲, 没问题.

但是 bug free 的要求太低了, 工程要有工程的样子.

**1.2.1** Worker

比方说 `worker`, 如果我们有个 `subprocess` 或者是 `popen` 的等价模型封装与底层操作系统打交道的细节, 仅暴露进程模型的行为:

1. 如果是进程模型, 那么可以表达的行为是 `Thread` 等价的高等抽象: `start`, `terminate`, `join`, `is_alive`
2. 如果是 popen 模型, 那么行为可以是更加暴露进程细节的: `wait`, `poll`, `terminate`, `kill`

那么最后 `os.fork` / `os.kill` / `os.wait` 这些与操作系统打交道的东西就能够被限制在模型边界之内, 而不是满世界飞 `os.fork`; 同时这样完成了与操作系统细节的分层, 便于解耦了抽象和实现, 虽然 Python 解释器已经帮我们处理了不同平台的进程细节, 但是假如我们要把 worker 从多进程模型改为多线程模型 (不考虑 GIL 哈), 这时候 Worker 模型只是实现发生了改变, 但是对上层结构来说所调用的 API 是毛都没变, 这是解耦带来的好处.

BTW, 如果真要改成多线程模型的话, GoF Bridge 模式和依赖倒置原则是指导思想, 就不展开了, 大家可以自己思考.

**1.2.2** Arbiter

`Arbiter` 这个[类](https://github.com/benoitc/gunicorn/blob/19.9.0/gunicorn/arbiter.py#L23), 在 docstring 里是这样描述职责的:

```
Arbiter maintain the workers processes alive.
It launches or kills them if needed.
It also manages application reloading via SIGHUP/USR2.
```

但是在刚才的进程抽象之下, 我们会发现 `arbiter.workers` 与其只是一个 array of worker, 不如抽象成为一个 WorkerManager 更好, 这是很常见的思路, Pool (ConnectionPool, ThreadPool, ProcessPool) 表达一个资源的聚合, 并定义在其之上的行为, 非常内聚.

这样一来, Arbiter 的方法 `manage_workers` / `murder_workers` / `reap_workers` 就迁移到 WorkerManager 上了, Arbiter 的职责就变成了管理 WorkerManager 实例和管理信号, 甚至连进程模型都不被暴露在顶层 API 中, 这是好事, 原来的大泥球模型已经变成了 `Arbiter -> WorkerManager -> Worker` 这样的三层抽象, 甚至还可以往下加一层 `-> WorkerImpl`, 如果有多重实现的需求的话.

#### 1.3. 事件循环

当然最糟糕的部分还是 Arbiter 里调度的部分, 也就是一开始所展示出的 `while True` 循环.

当然你可以说它很精妙, 阻塞在 `select.select` 上的 `self.sleep`, 信号处理优先级高于进程管理, 各种令人咂舌小细节, 像是一台精密的机械手表; 但是坏处也太多了, 首先难以理解, 其次假如我现在要再加入一种事件去调度, 比方说 Arbiter 同时还管理着 worker 的进程锁之类的, 或者再加入一些条件奇怪的定时器(给 Arbiter 集群的 leader 上报状态 / 响应扩容缩容请求), 那么用同步式的代码就开始捉襟见肘了.

该怎么办呢?

古典的方式, 当然全部用多路复用的方式撸起来, 注册事件和回调, `while True` 循环里就变成了:

```
while True:
    for event in event_loop.select():
        event.callback()
```

还行, 挺干净, 除了把事件循环暴露在顶层业务之外, which 也是一个大问题, 我向来讨厌业务暴露实现.

现代的方式, 当然是用 Gevent `monkey.patch_all()` + `gevent.spawn` 进行协程化, 但是会导致 fork 出来的子进程也被 monkey patch 了且不能 unpatch, 那么就完全行不通了, 因为为了利用 Django 的 DB Pool 有些业务还只能用 gthread 多线程并发模型, 不能 monkey patch.

或者是利用线程? 小规模的线程池好像也还行, 但是可扩展性捉急, 而且多线程 debug 比协程困难, race condition 比协程更加出现. 而且我对线程过敏, 听到这个词就害怕.

感觉要撸轮子才行了.

### 2. Arbiter: reboot

因为懒得画 UML, 所以直接张口就来:

#### 2.1. Coroutine

不知道为什么连个能用的 Coroutine API 都没有, 照抄 Thread API 就可以了.

1. `Coroutine(target, args, kwargs, *, greenlet)` 创建 coroutine
2. `coroutine.start()` 开始执行 coroutine
3. `coroutine.is_alive()` 是否结束运行
4. `coroutine.join()` 挂起当前协程, 等待调用 `join` 的 coroutine 完成运行
5. `coroutine.resume()` 恢复执行

#### 2.2. Popen

因为 Popen 模型的 API 比较简单, 所以直接照抄就可以了:

1. `Popen(callable)` 创建 popen 并 fork 子进程运行 callable
2. `popen.poll(flag=os.WNOHANG)` 检查子进程是否结束, 返回子进程退出码或者 None
3. `popen.wait(timeout=None)` 挂起当前协程, 等待子进程退出
4. `popen.terminate()` 向子进程发送 SIGTERM 信号
5. `popen.kill()` 向子进程发送 SIGKILL 信号

#### 2.3. Worker Manager

1. `WorkerManager(func, replicas, graceful_timeout, heartbeat_timeout)` 创建 worker manager, 发送 SIGTERM 之后 `graceful_timeout` 发送 SIGKILL, `heartbeat_timeout` 之内没有心跳则杀掉子进程
2. `worker_manager.run()` 拉起子进程, 维护子进程
3. `worker_manager.stop()` 停止子进程
4. `worker_manager.purge()` 杀掉所有子进程
5. `worker_manager.maintain()` 维护子进程的数量, 多则杀, 少则加, 另外处理死掉的子进程尸体
6. `worker_manager.incr_worker()` 增加一个子进程
7. `worker_manager.decr_worker()` 减少一个子进程

#### 2.4. Arbiter

那么 Arbiter 的职责就很简单了, 我们甚至可以立刻把代码写出来:

```python
class Arbiter(object):
    SIGNAL_NAMES = 'HUP QUIT INT TERM CHLD TTIN TTOU'.split()

    def __init__(
        self, entry_func, replicas, graceful_timeout=30, heartbeat_timeout=30
    ):
        self.running = False

        self.worker_manager = WorkerManager(
            entry_func,
            replicas,
            graceful_timeout=graceful_timeout,
            heartbeat_timeout=heartbeat_timeout,
        )

        self.graceful_timeout = graceful_timeout

    def run(self, **context):
        self.add_signal_handlers()

        # TODO: daemonize
        self._run()

    def _run(self):
        coro = Coroutine(target=self.worker_manager.run).start()

        self.running = True
        while self.running:
            coroutine.sleep(1)

        logger.info('[arbiter] exiting')
        self.worker_manager.stop()
        coro.join()
        sys.exit(0)

    def add_signal_handlers(self):
        for signal_name in self.SIGNAL_NAMES:
            sig = getattr(signal, 'SIG' + signal_name)
            handler = getattr(self, 'handle_' + signal_name)
            coroutine.signal(sig, handler)

    def handle_HUP(self, signum, frame):
        logger.info('[arbiter] handling signal HUP')
        self.worker_manager.purge()
```

这里只实现了 SIGHUB handler, 不影响理解. 总之 Arbiter 只做三件事: 安装信号, 启动 `worker_manager` 协程, 睡觉等待退出. (可能会有第四件事, daemon 管理, 和第五件事, 配置管理, 懒, 以后再说)

这才是我想要的.

在进入在实现细节之前, 先讨论一些设计上的问题.

#### 2.5. FAQ

**2.5.1.** 异步和同步

具体来说:

- `worker_manager.run()` 应该阻塞当前协程还是默认创建新协程并立刻返回, 或者加入一个参数 `run(async=True)` 控制是否异步?
- `worker_manager.stop()` 同上?
- `popen.wait(timeout)` ?
- ...

这个问题是有迷惑性的, 稍不注意会就从业务层传递一个 `async` 变量到 `Popen` 实例上, 或者更糟糕的是直接默认一些 API 是异步执行.

这两种设计都特别糟糕, 前者让调度侵入了一个底层的模型, 后者更加完全没有道理, 哪些是异步哪些是同步基本靠我的心情, 经常上午写完下午就觉得似乎应该改过来, 完全乱套了.

所以我全部默认所有 API 都是同步执行, 若要异步必须显式创建 Coroutine 实例并 start, 像 Thread 一样去调用 API, like `Coroutine(target=popen.wait).start()`.

**2.5.2.** 职责

来看这几个问题:

- 注册信号处理器的时候可以调用 `event_loop.add_signal_handler` 吗?
- SIGHUP 处理器里应该遍历 `worker_manager.popens` 再依次 `popen.terminate` 对吗?
- 应该在 SIGCHLD 处理器里调用 `os.waitpid` 再 `worker_manager.reap_process(pid)` 吗?

三个问题虽然各有各的迷惑性, 但是本质都是在探讨模型的职责.

第一个问题, 不可以.

`event_loop.add_signal_handler` 是 coroutine 之下的实现细节, 除了 coroutine 相关模块之外, 不应该出现在任何地方. 是, 我想表达的是显式注册协程信号处理器, 不想用 `signal.signal` 再 monkey patch, 但是应该调用的是 `coroutine.signal` 这样的函数, 其中 `coroutine` 是模块名.

第二个问题, 不可以.

没错, SIGHUP 信号的处理逻辑确实是依次对 popen 实例执行一遍 terminate, 但是这不应该让 signal handler 去调用, 而是 worker manager 的职责. 换句话说, signal handler 只负责调用 `self.worker_manager.purge()`, 至于 popen 什么的, 那是 WorkerManager 的实现细节, 怎么能暴露在模型边界之外.

第三个问题, 不可以.

SIGCHLD 应该是最具迷惑性的实现细节, 用脚稍微一想就能有以下的实现方式:

1. `os.waitpid` 拿到 pid, 传给 `worker_manager.reap_process(pid)`
2. 遍历 `worker_manager.popens`, 依次调用 `popen.poll()`
3. 写一个管道或者 eventfd 什么的触发 `worker_manager.reap_children()`

当然, 这些都能 work, 但是, 都多少破坏了抽象.

1. 进程模型完全被 Popen 模型封装了, 其他任何地方都不应该出现 `os.wait*` 系列
2. 同第二个问题, popens 是 WorkerManager 的实现细节, 甚至是私有成员, 不应该暴露
3. 当然很巧妙, 甚至看起来很牛逼, 但是又把底层事件循环的实现细节暴露到业务层了, 这一直是我嗤之以鼻的

最后经过权衡, 我把收割子进程的变成了一个定时轮训, 虽然看起来没有用信号触发事件循环那么牛逼, 但是这里的轮训开销微不足道, 但是带来的好处却太大了, 我们保持了抽象和模型边界的清晰和完整.

这些思路贯穿整个代码, 指导了所有细节设计, 不再赘述.

### 3. Implementation: Coroutine

这里面最有趣的部分当属实现 `coroutine` 模块, 它封装了基于多路复用的事件循环, 完全改变了程序运行流, 但是却没有暴露 EventLoop (想想 Tornado 这个 IOLoop 暴露狂).

说真的怎么会到现在 Python 工业界连一个 Thread 等价 API 的 Coroutine 都没有, 匪夷所思...

以下是 spec:

#### 3.1. Motivation (or 公审: Gevent)

Gevent 当然有它的好处, 比如工业成熟, 外部 API 也很优秀, 中规中矩地使用不至于 surprise, 但是它的槽点是:

1. 为啥不用 signalfd / eventfd / timerfd? 比如一想到 `time.sleep` 协程化, 第一反应就是 `timerfd_create(2)`, 但是不知道为什么他们不用.
2. 协程 Queue 的阻塞居然不是靠事件循环 trigger 的. 这导致 `queue.get(block=True)` 在 `monkey.patch_all(thread=False)` 的情况下居然会出现奇怪的报错, 无法理解为什么不用显而易见的实现方式.
3. 实现里的抽象很奇怪, 我意思是, 我当然知道那些模型 (like [Hub](http://www.gevent.org/api/gevent.hub.html#gevent.hub.Hub)) 的职责是什么, 但是为什么需要那些奇怪的模型, 我完全一头雾水.

所以我决定自己撸一个基于 Greenlet 的协程模块, 同时希望能够(尽可能)兼容 [pep-3156](https://www.python.org/dev/peps/pep-3156/).

#### 3.2 Rationale

总之考虑以下的代码:

```python
def sleep(sec):
    event_loop = EventLoop.get_instance()
    event_loop.call_later(sec, _resume_current())
    _yield_current()


def _yield_current():
    _get_event_loop_coroutine().resume()


def _resume_current():
    coro = Coroutine.current()
    return coro.resume


def _get_event_loop_coroutine():
    global EVENT_LOOP_COROUTINE
    if not EVENT_LOOP_COROUTINE:
        event_loop = EventLoop.get_instance()
        EVENT_LOOP_COROUTINE = Coroutine(target=event_loop.run_forever)
    return EVENT_LOOP_COROUTINE
```

当协程 A 执行到 `sleep(1)` 的时候, 会先往 `event_loop` 里注册回调, 回调事件就是 resume 当前协程; 然后立刻切换到 `event_loop.run_forever()` 的协程 (叫它事件协程), 挂起当前协程 A; 最后事件协程调度到这个 timerfd 事件后, 运行回调函数, 切换回到协程 A, 事件协程挂起.

至于 EventLoop 和 Coroutine 的实现, 前者就是套了上 `selector`, 调用 timerfd 的一个 [pep-3156](https://www.python.org/dev/peps/pep-3156/) 子集, 没啥好说的; 后者就是 Greenlet 的封装, 也没啥好说的, 有兴趣的人直接去看仓库吧.

不过几点有趣的细节需要说一下:

**3.2.1.** FDPool

在 EventLoop 里创建 timerfd / signalfd 的时候, 我是通过 `fd_pool` 这层抽象去获取的:

```python
class EventLoop(object):
    def call_later(self, delay, func):
        fd = self.fd_pool.get_timerfd(delay)
        self.add_reader(fd, TimerEvent(fd, func).callback)

    def add_signal_handler(self, sig, func):
        fd = self.fd_pool.get_signalfd(sig)
        self.add_reader(fd, SignalEvent(fd, func).callback)
```

这样做最大的好处是资源集中分配, 可追溯分配了的文件描述符; 这非常重要, 因为 fork 出来的子进程不会 exec, 所以继承过去的文件描述符不会关闭 (close-on-exec flag); 如果我们有统一的文件描述符分配池, 在 fork 之后调用一次 `fd_pool.close_on_fork()` 就可以了.

BTW, 更好的做好不是在 fork 后调用 `fd_pool.close_on_fork()`, 而是采用好莱坞风格, 把 `fd_pool.close_on_fork` 注册到, 比如叫做 `post_fork` 什么鬼的对象上, 大概这样, Whatever.

**3.2.2.** exec

其实我是很想 fork 之后 exec 的, 关闭无用的 fd 什么的就不说了, 最主要的是 worker 经常在 fork 之后再 `gevent.monkey.patch_all()`, 太晚了, 内存里已经载入了真 Thread 之类的东西无法 patch, 然后就会有各种 shit.

然而我们需要让多个进程 accept 同一个套接字, 而套接字共享的正统方式就是 fork 继承, NGINX 都是这么干的; 至于通过 Unix 套接字传递什么的, 都是太奇怪了, 更别说 NGINX 不仅依赖 fork 继承套接字, 它那牛逼的惊群自旋锁都是通过 fork 继承过去的, exec 反而不现实.

~~正解: 换成 Golang.~~

**3.2.3.** Coroutine.join

这个 API 是非常重要的, 考虑一下 `WorkerManager.run()`:

```python

class WorkerManager(object):
    def run(self):
        self._running = True
        while self._running:
            Coroutine(target=self.maintain).start()
            coroutine.sleep(1)

        self.replias = 0
        self.purge()

    def purge(self):
        logger.info('[arbiter] kill all children')

        coros = []
        while self._popens:
            popen = self._popens.pop()
            coro = Coroutine(
                target=self._gracefully_terminate, args=(popen, self.graceful_timeout)
            )
            coro.start()
            coros.append(coro)

        for coro in coros:
            coro.join()

    def stop(self):
        self._running = False
```

注意到在 `worker_manager.purge()` 里我们是如何**并发地**杀死子进程(因为杀死子进程搞不好需要 `graceful_timeout` 这么久的时间, 不可能同步), 最后再依次 join. 本质上, 这是 CoroutinePool 抽象, 但是我懒得实现了.

回到实现细节上, 为了让协程阻塞在 join, 我采用了 eventfd:

```python
class Coroutine(object):
    def join(self):
        if not self.is_alive():
            return

        def callback(resume, event_loop):
            event_loop.del_reader(self._finish_fd)
            resume()

        event_loop = EventLoop.get_instance()
        self._finish_fd = self._fd_pool.get_eventfd()
        event_loop.add_reader(self._finish_fd, partial(callback, _resume_current()))
        _yield_current()
```

应该很好理解, just FYI.

(BTW, 不用 eventfd 应该怎么实现, 我头发抓秃都想不出, Gevent 是魔鬼吗?)

### 4. For the Greater Good

框架基本出来了, 但是还有一些尚未提及的细节需要谈一下.

#### 4.1. heartbeat

在 Gunicorn, 心跳是通过子进程调用 `os.fchmod` 修改临时文件的 ctime 去做的, 比如 gevent worker 就每秒心跳, gthread worker 就每次 accept 之前心跳.

那我有这样几个问题:

1. 我可以用发送信号代替修改文件作为心跳吗?
2. 我可以用 pipe 作为心跳吗?

Roughly speaking, 可以, 但是它们的问题是大量无用的系统调用.

比方说在 gthread worker 下, 假如流量 spike, 一瞬间每个 worker accept 1000 个请求(默认的 `worker_connections` 是 1k), 那么需要发送 N * 1000 个信号给 Arbiter, 或者写 N * 1000 个字节进入 pipe; 就算 pipe 或者 signalfd 缓冲区较小, 不会消耗大量内存, 同时 pipe 为 nonblocking 模式不会导致写阻塞, 但是与修改文件相比, 每次心跳都会有额外的 IPC overhead, worker 每次心跳都通知到 arbiter, 这就很没必要, arbiter 只要每隔几秒检查一次就可以了, 否则内核也会更加忙碌.

touch file 的问题是 disk IO 是一个令人感到害怕的东西, 不可控, D 状态了解一下, 但是假如说摸一个文件都 D 了, 那整个文件系统显然已经完全不正常了, 也别指望 worker 能正常运行, 日志肯定也打不出, 那还指望什么心跳..

#### 4.2. graceful termination

graceful termination 的重要性不言而喻, 尤其是队列 consumer 之类的 daemon.

Generally, 它有以下几个步骤:

1. 不再接收新的消息. 对于队列 consumer 就是不再取消息, 对 tcp 服务来说要先 close listening socket, 不过这里有个问题是 backlog 里已经完成了三次握手的请求会被 FIN, 著名的 `upstream prematurely closed connection` 报错了解一下.
2. 接着处理完已经 accept 的请求.
3. 若在 graceful timeout 时间内处理完, 直接退出; 否则强退, 否则 FIN.

实现起来的话问题也不大, spawn 一个协程 / 线程计时器就可以了, 不过 Gunicorn 的做法是 countdown, 每秒去轮询一下请求有没有处理完.

另外一个问题在 Gunicorn 把 timeout kill 的职责扔给了 worker, 在我的实现里这是 arbiter 的工作, 发送 SIGTERM 之后 调用 `popen.wait(graceful_timeout)`, 如果超时再 SIGKILL.

#### 4.3. daemon

想写好 daemon 也困难重重, 所以我们有 [pep-3143](https://www.python.org/dev/peps/pep-3143/).

简单来说一个最基本的 daemon 是这样的:

1. 第一次 `fork`, 让父进程死掉, 这样子进程被一号进程收养. 这样 fork 出来的子进程也能成为进程组 leader, 这是下一步的前提.
2. 子进程调用 `setsid` 变成 session leader, 从而完全脱离之前的控制终端A.
3. 第二次 `fork`, 让子进程不再是 sesesion leader, 从而不可能获得控制终端.
4. 清理进程 umask, 保证 daemon 创建文件时有权限.
5. 切换进程的工作目录, 比如到根目录, 以防 daemon 占用了某个路径导致相应的文件系统不能 unmount.
6. 关闭从父进程继承的文件描述符, 除非有特殊需要, 比如继承的 socket.
7. 用 `dup2` 把 0 / 1 / 2 三个文件描述符指向 `/dev/null` 或者指定的文件, 避免某些 lib 默认输出到 0 / 1 / 2 出错.

当然进一步来说, pidfile 什么的也是必须的, SIGHUP / SIGUSR1 的处理也必须正确, 基本就是 arbiter 里的其他那些鬼东西.

不过 daemon 在容器化时并不受推荐, 因为 daemon 的前提是有个靠谱的 1 号进程, 收割僵尸和转发信号是最最基本的要求, 然而部分公司的做法却是:

1. 让 gunicorn arbiter 作为 1 号进程, 1 / 2 描述符全部打到终端, 给 Docker daemon 造成很大的日志搜集负担. 这还算好的, 更惨的是:
2. 把服务注册作为一号进程, 如果是依赖某些 runtime 环境才能注册的话(听上去就是其他环节坏掉了, 没错), 也只能这么干, 结果这个 1 号连僵尸都不能收割, 更别说转发信号.
3. supervisord? 建议先去看看它的 [open issues](https://github.com/Supervisor/supervisor/issues), 简直想笑, 典型的 web 程序员强行装逼的下场, Unix 编程这种瓷器活我看大部分____还是别碰最好.

(sigh~

#### 4.4. concurrency pattern

协程模型下的可控并发模式, 至少要有以下几点:

1. 资源消耗可控, 这就意味着你不能来一个请求 spawn 一个协程, CoroutinePool 是必须的.
2. 流程可控, 意味着 SIGTERM 一收到就能立刻控制协程不再收新消息.

很容易想到的方式就是一个 `Pool(1000)`, 然后一个 while 循环收消息, 再无脑 `pool.spawn(handle, msg)`:

```python
pool = gevent.Pool(1000)
while running:
    msg = get_msg()
    pool.spawn(handle, msg)

# graceful termination below
```

这样做是没错啦, 只是大量的创建 / 销毁协程的 overhead 其实我们也可以避免的, 但是需要一个额外的 relay.

```python
class Consumer:
    def __init__(self):
        self._queue = gevent.Queue(100)

    def produce(self):
        while self._running:
            msg = get_msg()
            while True:
                try:
                    self._queue.put(msg, timeout=1)
                    break
                except Full:
                    continue

        self._queue.put(DoneEvent())

    def poll_and_handle(self):
        while True:
            try:
                msg = self._queue.get(block=False)

            except Empty:
                gevent.sleep(1)
                continue

            except gevent.hub.LoopExit:
                # gevent stupid bug
                log.exception()
                continue

            else:
                if isinstance(msg, DoneEvent):
                    break
                self.handle(msg)

        self._queue.put(msg)
```

这样做的好处是:

1. 让 `self.produce` 控制流程, 当 `self._running` 为 False 时不再接收消息, 同时 poller 也能收到结束通知
2. `self.poll_and_handle` 为一个固定数量的协程池在运行, 这些协程不会销毁, 避免了相应 overhead
3. 在 `get_msg` 会阻塞事件循环的情况下, 比如使用 C 实现的 confluence-kafka lib 无法做 patch, 这时候我们可以让 `self.produce` 跑在一个真线程里, 不过要注意 `monkey.patch_all(thread=False)`

此外, 还要注意可能需要对协程进行一个简单的管理, 就像 arbiter 一样监控协程的数量, 如果有遇到异常退出的需要补充协程, 小事一桩.

### 5. Bigger Picture

最后让我们退后一步, 看看我们做的是一个什么事情.

我们现在有的一个框架, 它只关心 fork 进程, 然后运行我们传入的 callable, 最后做一些相应的监控和管理.

来看两个实际用例.

#### 5.1 queue consumer

```
pool = gevent.Pool(1000)
def poll_and_handle():
    msg = get_msg()
    pool.spawn(handle, msg)

arbiter = Arbiter(poll_and_handle, replicas=4, graceful_timeout=30)
```

很偷懒了, 而且 graceful termination 的逻辑也应该自己注册信号处理器, 但是会发现, 事情好像简单多了.

#### 5.2 UDP + Unix Socket Server

server 要复杂一些, 要提前创建套接字, 不过也问题不大:

```python
class Worker(object):
    def __init__(self, sock, worker_connections=1000):
        self.sock = sock
        self.worker_connections = worker_connections

    def run(self):
        self.setup()

        self.server = gevent.DatagramServer(
            listener=self.sock, handle=self.handle, spawn=self.worker_connections
        )
        self.server.serve_forever()

    def setup(self):
        self.pid = os.getpid()
        logger.info('[worker %s] launching' % self.pid)

        from gevent import monkey
        monkey.patch_all()

        gevent.signal(signal.SIGTERM, self.term_handler)

    def term_handler(self):
        logger.info('[worker %s] exiting', self.pid)

    def handle(self, data, address):
        logger.info('[worker %s] handling: %s', self.pid, data)


sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
address = '/var/run/worker.sock'
if os.path.exists(address):
    os.unlink(address)
sock.bind(address)

worker = Worker(sock)
arbiter = Arbiter(worker.run, replicas=2, graceful_timeout=30)
```

也是非常容易.

仔细一想, 甚至连 Gunicorn 我们都可以用这个框架去实现. 所以这个框架最后成了 Gunicorn 的 superset, 真是令人性奋.

其实早就该有这么一个框架了, 我早就想打人了, 好了我现在要写周报了, 进度已经滞后到自暴自弃了, 去他妈的.
