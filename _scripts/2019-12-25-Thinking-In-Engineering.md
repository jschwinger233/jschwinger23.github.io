---
layout: post
---

2015 年 12 月 18 日周五, 我在北京找到了第一份程序员工作, 一蹦一跳从望京出来.

2016 年的生日, 我在空间里写下 "我非常害怕，一年后，两年后，三年后，四年后的我，拿着别人看来还不错的薪水，却在数据库底层、操作系统底层，HTTP 协议、并发、分布式系统都没有深入地理解，掌握着一门或者几门脚本语言写个 C++ 却 BUG 辈出。我觉得特别害怕。"

你看转眼就是四年后了, 我走了一万一千里路站在这里, 总算培养出一些评判代码好坏的纲领, 索性记录一下当前对工程的思考.

# 1. 并发

并发这个主题早在 2018 年 6 月乘坐悉尼到 New Castle 的火车时就思绪万千了, 当时读着都能背诵下来的 Python Cookbook 第 13 章, 心里想着各种各样的话题: 惊群, 自旋锁, self-pipe trick...

## 1.1 Context

奇怪的是只有 Go 才把 Context 作为核心抽象, 而其他语言(Python, Rust)要实现类似的功能都很扭曲, 以至于有时候你已经实现了一个 Context 但你自己都没意识到这就是 Context.

先跳出来思考, 在没有 Context 的世界一般我们是如何中断一个正在运行的线程/协程(以下简称`*程`)的:

1. 通过变量在旁路控制

也就是说消费者在取消息前都先判断一个布尔变量 `running`, 若为 false 则不再消费. 注意由于设置变量不具备通知能力, 所以可能要在取消息前后都要检查一次变量:

```
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

```
def run():
    while True:
        readable, _, _ = select([queue, pipe], [], [])
        if pipe in readable:
            return
        if queue in readable:
            msg = queue.get()
```

我们会发现这本质上和 Go 的 Context 用法是一样的.

这里的本质思想是对*程的控制.

思考题: 实现线程版本的 `gevent.Timeout`:

```
try:
    with timeout(1):
        do()
except Timeout:
    pass
```

## 2. fan-out, fan-in

我们要做大量的 etcd get, 想用 etcd bulky get 来提升性能, 然而 etcd bulky get 一个请求只能携带... 忘了多少个 key 了, 假设 150 个吧, 因此我们要用多个*程发 bulky get 最后把结果收回来.

这件事情在 Python 里特简单, 直接 `concurrent.futures` 一波带走:

```python
```

但是用 Go 来做的话, 如果让小朋友来写的话第一次不是不知所措就是死锁.

这里有好几种思路, 但是最成熟的做法应该是用 fan-out fan-in pattern:

```go
```

要注意这里的要点是 Go channel 只能 close 一次, 因此最好保证只有一个 goroutine 写 channel, 否则多个 goroutine 写完后必须有一次同步才能 close.

有趣的是在 Rust 标准库里提供的 channel 是截然相反的 `std::sync::mpsc`, 即 multi-producer single-consumer FIFO, 这是因为 either 你可以用 `Arc<Mutex<Receiver<T>>>` 来做到 multi-consumers, or 可以用 crossbeam channel 轮子来完成.

最后再来看看 Go 版本的 concurrent.futures 和 Python 版本的 fan-out fan-in:

```go
```

```python
```

任何一个成熟的工程师都应该能够在一开始的 etcd bulky get 问题上立刻映射到 fan-out fan-in pattern, 这题也在我的面试题库中用来衡量一位 Go 程序员的专业程度.

## 3. leak

## 4. timeout

## 5. graceful termination

## chewing over: high level abstract of goroutine in Go

## chewing over: correct abstract for coroutine in Python

1.2 curd
restful api design, pagination
architecture: layer
modeling

1.3 os
signal
process management: dumb-init, daemon, pid 1
terminal
