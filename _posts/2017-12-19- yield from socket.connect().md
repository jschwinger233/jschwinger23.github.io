在我还很年少幼齿的时候，突然有一天看到 Tornado，它居然在文档里说它的异步代码是酱紫的：

```python
from tornado import gen

@gen.coroutine
def fetch_coroutine(url):
    http_client = AsyncHTTPClient()
    response = yield http_client.fetch(url)
    raise gen.Return(response.body)
```

太颠覆性了，对我的冲击无异于初一熬夜刷完伊藤润二《旋涡》，我整个人都陷入了巨大的幸福的旋涡之中。

后来我尝试努力去看它的源码，试图理清它背后做的事情，然而完全没有头绪。这个未解之谜被我列为 2017 年度计划之一。

Time goes by, so slowly.

---
<br />

今天我要做的事情，是实现这样一个模块 `Aevent`（名字毫无疑问抄袭 `Gevent` 这种天才绝伦的库，就和垃圾 JavaScript 抄袭~~天才绝伦的~~ Java 一样），它提供了以下的 API:

0. `aevent.monkey.patch_socket()`，毫无疑问抄袭天才绝伦的 `gevent.monkey.patch_socket()`，你可以简单理解为把标准库的 `socket.socket` 变成一个奇怪的东西。
1. `aevent.spawn`，毫无疑问抄袭天才绝伦的 `gevent.spawn`，你可以简单理解为新创建一个协程进入主事件循环。
2. 需要 explicit 对有网络调用（有 IO Blocking）的地方使用 `yield from`，示范：`resp = yield from requests.get()`
3. 没有了

然后你就拥有了魔法，在单进程单线程里多路复用地运行你的花式网络调用。

不妨先看一下，这是我们的一个简单的 TCP Echo Server，干了很简单的几件事：

1. 监听 8000 端口
2. 处理 client 的连接，接收 client 发送过来的东西
2. 转发请求到一个号称 slow echo server 的服务上, which 也是一个 TCP Echo Server，只不过对每个请求需要睡 1s 才能响应。
3. 收到 slow echo server 的响应，把消息回复给 client

```python
import os
import socket
from logging import getLogger

logger = getLogger(__name__)
SLOW_ECHO_SERVER_PORT = os.environ.get('SLOW_ECHO_SERVER_PORT', 9000)


class Server:
    def __init__(self, port, backlog=500):
        self.port = port
        self.backlog = backlog
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ready()

    def ready(self):
        self.sock.bind(('', self.port))
        self.sock.listen(self.backlog)
        logger.info('listening on port %s', self.port)

    def serve_forever(self):
        while True:
            peer, addr = self.sock.accept()
            self.handle_peer(peer, addr)

    def handle_peer(self, peer, addr):
        raise NotImplementedError


class M0Server(Server):
    def handle_peer(self, peer, addr):
        words = peer.recv(1024)
        logger.info('M0 echo server recv %s from peer %s', words, addr)
        peer.send(self.request_slow(words))
        peer.close()

    def request_slow(self, text):
        logger.info('prepare to relay to slow echo server')
        req_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        req_sock.connect(('', SLOW_ECHO_SERVER_PORT))
        req_sock.send(text)
        return req_sock.recv(1024)


if __name__ == '__main__':
    server = M0Server(8000)
    server.serve_forever()

```

对就是这样。为了方便复用我直接写了基类，之后的代码直接在此之上 override。

先来随手测一下并发处理能力：

```shell
(aevent) lzc:aevent zc$ make M0
python -m src.M0.server
[INFO][2017-12-22 00:46:36,859][server][listening on port 8000]
[INFO][2017-12-22 00:47:06,057][server][M0 echo server recv b'123\n' from peer ('127.0.0.1', 54505)]
[INFO][2017-12-22 00:47:06,057][server][prepare to relay to slow echo server]
[INFO][2017-12-22 00:47:07,062][server][M0 echo server recv b'123\n' from peer ('127.0.0.1', 54506)]
[INFO][2017-12-22 00:47:07,062][server][prepare to relay to slow echo server]
[INFO][2017-12-22 00:47:08,065][server][M0 echo server recv b'123\n' from peer ('127.0.0.1', 54508)]
[INFO][2017-12-22 00:47:08,065][server][prepare to relay to slow echo server]
```

实在是惨不忍睹，每一个请求都必须等到上一个请求完全处理完毕才能被服务器处理，就算每个请求有一秒的时间阻塞在 IO 上、等待一个不知道什么时候才能回来的 TCP 消息。

是时候改变这种窘境了！

首先我们来看一下，使用 gevent 来改造的话，大概是以下这样：

```python
import gevent
from gevent import monkey
monkey.patch_socket()

import os
import socket
from logging import getLogger

from ..common.server import Server

SLOW_ECHO_SERVER_PORT = os.environ.get('SLOW_ECHO_SERVER_PORT', 9000)
logger = getLogger(__name__)


class M1Server(Server):
    def serve_forever(self):
        while True:
            peer, addr = self.sock.accept()
            gevent.spawn(self.handle_peer, peer, addr)

    def handle_peer(self, peer, addr):
        words = peer.recv(1024)
        logger.info('M1 echo server recv %s from peer %s', words, addr)
        peer.send(self.request_slow(words))
        logger.info('M1 echo server response peer %s with %s', addr, words)
        peer.close()

    def request_slow(self, text):
        logger.info('prepare to relay to slow echo server')
        req_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        req_sock.connect(('', SLOW_ECHO_SERVER_PORT))
        req_sock.send(text)
        return req_sock.recv(1024)


if __name__ == '__main__':
    server = M1Server(8000)
    gevent.spawn(server.serve_forever())
```

对主要的代码逻辑几乎一字不改，完美，再测一下性能：

```shell
(aevent) lzc:aevent zc$ make M1
python -m src.M1.server
[INFO][2017-12-22 00:50:16,968][server][listening on port 8000]
[INFO][2017-12-22 00:50:22,097][server][M1 echo server recv b'123\n' from peer ('127.0.0.1', 54531)]
[INFO][2017-12-22 00:50:22,098][server][prepare to relay to slow echo server]
[INFO][2017-12-22 00:50:22,134][server][M1 echo server recv b'123\n' from peer ('127.0.0.1', 54532)]
[INFO][2017-12-22 00:50:22,134][server][prepare to relay to slow echo server]
[INFO][2017-12-22 00:50:22,134][server][M1 echo server recv b'123\n' from peer ('127.0.0.1', 54534)]
[INFO][2017-12-22 00:50:22,135][server][prepare to relay to slow echo server]
[INFO][2017-12-22 00:50:23,139][server][M1 echo server response peer ('127.0.0.1', 54532) with b'123\n']
[INFO][2017-12-22 00:50:24,140][server][M1 echo server response peer ('127.0.0.1', 54534) with b'123\n']
[INFO][2017-12-22 00:50:25,146][server][M1 echo server response peer ('127.0.0.1', 54531) with b'123\n']
```

wow，服务器阻塞在 IO 上的同时也能够处理其他的请求，真是太感人了。

那么我现在想做的事情呢，是用 aevent 实现这样的代码：

```python
from . import aevent
from .aevent import monkey
monkey.patch_socket()

import os
import socket
from logging import getLogger

from ..common.server import Server

SLOW_ECHO_SERVER_PORT = os.environ.get('SLOW_ECHO_SERVER_PORT', 9000)
logger = getLogger(__name__)


class M4Server(Server):
    def serve_forever(self):
        while True:
            peer, addr = yield from self.sock.accept()
            aevent.spawn(self.handle_peer, peer, addr)

    def handle_peer(self, peer, addr):
        words = yield from peer.recv(1024)
        logger.info('M4 echo server recv %s from peer %s', words, addr)
        yield from peer.send((yield from self.request_slow(words)))
        logger.info('M1 echo server response peer %s with %s', addr, words)
        yield from peer.close()

    def request_slow(self, text):
        logger.info('prepare to relay to slow echo server')
        req_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        yield from req_sock.connect(('', SLOW_ECHO_SERVER_PORT))
        yield from req_sock.send(text)
        return (yield from req_sock.recv(1024))


if __name__ == '__main__':
    m4_server = M4Server(8000)
    aevent.spawn(m4_server.serve_forever)
```

emm，比 gevent 糟糕一点（其实是糟糕太多了，然而我实在不愿意用 ast 魔改，那样的东西就算做出来也只是玩具，因为你的 exception traceback 会惨到不能看，Sentry 一类的东西完全跪了。）

可以看到比 gevent 逊色的地方在于，需要手动 `yield from` 去声明 `这是一个 IO 阻塞的函数调用`，非常低级。但是很多（or 有些）时候我们就是希望这样笨拙的声明，thus 我们才能控制一切阻塞点。

`Explict is better than implicit`，行了这地我洗不下去了。

所以不管你多么 diss 这个 API，我们的目标还是明确了。

提醒一下看官，这个 API 可比 Tornado 高到不知道哪里去了哦：

1. Tornado 必须用奇怪的装饰器 `gen.coroutine` 把从上往下的调用栈上的一切函数都 wrap 起来，而 Aevent 完全不用
2. Tornado 必须用 `IOLoop().run_forever()` 啥的来声明 `我要开始滚动历史的车轮啦`，而 Aevent 完全不用

那么我们开始。
