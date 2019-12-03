---
layout: post
---

> 副标题: 我为什么觉得~~大~~部分同事是垃圾

2015 年冬我从非洲裸辞, 在北京找到了第一份程序员工作, 至今正好快四年了.

2016 年的生日, 我在空间里写下 "我非常害怕，一年后，两年后，三年后，四年后的我，拿着别人看来还不错的薪水，却在数据库底层、操作系统底层，HTTP 协议、并发、分布式系统都没有深入地理解，掌握着一门或者几门脚本语言写个 C++ 却 BUG 辈出。我觉得特别害怕。"

你看这就是第四年了, 我站在这里, where the streets have no name.

写了这么多垃圾代码, 我也总算培养出一些评判代码好坏标准的规则, 所以这次想谈谈(我所认为的)四年工程经验的程序员应该掌握的工程素养.

# 1. 并发

并发这个主题早在 2018 年 6 月乘坐悉尼到 New Castle 的火车时就想思绪万千了, 当时读着都能背诵下来的 Python Cookbook 第 13 章, 心里想着各种各样的话题: 惊群, 自旋锁, self-pipe trick...

## 1.1 Context

奇怪的是只有 Go 才把 Context 作为核心抽象, 而其他语言(Python, Rust)要实现类似的功能都很扭曲, 以至于有时候你已经实现了一个 Context 但你自己都没意识到这就是 Context.

先跳出来思考, 在没有 Context 的世界一般我们是如何中断一个正在运行的线程/协程(以下简称`*程`)的:

1. 生产者向队列插入 sentinel

```python
```

生产者消费者模型的好处在于临界区被严格控制在队列对象中, 因此极大减少了并发编程时数据同步的心智负担.

2. 通过变量在旁路控制

```python
```

这种做法的好处是简单, 事实上这是标准的 "接收信号退出事件循环结束进程" 做法, 也是我最喜欢的做法. 在接下来的 graceful termination 里还会遇到.

3. 通过 IO 多路复用在旁路控制

```python
// gunicorn
```

这就很妖了, 但其实这种做法有着通过变量控制所不企及的优势: 可以在 IO 阻塞处中断, 而上一种做法只能在 IO 恢复后回到循环里才能中断.

再看看 Go 里 Context 的典型用法:

```go
```

我们会发现其实这本质上居然是和第三种做法一样的, 都是阻塞在多个 IO 上通过多路复用接受旁路通知.

插入一句, Go Context 有一个问题是 regular file IO 无法被中断:

```go
```

这是由于 select / poll / epoll (以下简称`多路复用模型`)无法处理 regular file IO, 太菜了, 写得不好的话会造成严重的*程泄漏.

总结一下, Context 的本质思想是`中断*程`, 正确理解了这个思想的话那么应该在任何 IO 阻塞点监听 `<-context.Done()`; 此外用其他语言做并发开发时也应该考虑到这一点, 这就是我想表达的`工程素养`: 对*程的中断和控制是严格必须执行的.

用 Go 举两个极端的例子, 一般大家不会这么写:

```go
// context in loop
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
