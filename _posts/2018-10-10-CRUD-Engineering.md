---
layout: post
---

发现大家普遍对业务代码充满不屑, 张口 `CRUD 低级`, 闭口 `业务代码恶心`, 但是不巧的是我对 CRUD 有着截然不同的看法, 我觉得这件事非常高级, 高级到不是一般的程序员能够做得好的.

全文使用 Django, 因为我最熟悉.

> 当然代码都是随手写的

> API 什么的全凭记忆

> 不符合 PEP8

> 有错别字

---
## 一. 模型与 RESTful

我们要做一个语料管理系统, 经过与算法团队和产品经理团队的讨论, 大家拍板了以下的模型关系:

![](https://github.com/jschwinger23/jschwinger23.github.io/blob/master/data/curd-model.png?raw=true)

用人类的话说, 一个话题 (Topic) 包含多轮 (Round) 问答, 一轮问答包含多个问题 (Question) 和一个回答 (Answer).

现在要提供一些初步的 CRUD API,  我们先实现一个创建 API.

### 1.1 POST `/api/v1/topics/`

好了我直接把这个幼齿的 API 写出来了:

```python
# models.py

from django.db import models

class Topic(models.Model):
    id = models.AutoField()

class Round(models.Model):
    id = models.AutoField()
    topic = models.ForeignKey()

class Question(models.Model):
    id = models.AutoField()
    content = models.TextField()
    round = models.ForeignKey()

class Answer(models.Model):
    id = models.AutoField()
    content = models.TextField()
    round = models.OneToOneField()

# views.py

@require_GET
def create_topic_view(request):
    auth_id = request.META['X_AUTH']
    account = get_account_or_none(auth_id)
    if not account:
        return JsonResponse(..., 401)

    topic_info = json.loads(request.body)
    if account.product_id != topic_info['product_id']:
        return JsonResponse(..., 403)

    topic = Topic.objects.create()
    for round_info in topic_info['rounds']:
        ...

    return JsonResponse(
        {
            'id': topic.id, 
            'rounds': [...],
		}
	)

# urls.py

urlpattern = [url(r'^api/v1/topics/', views.create_topic_view)]
```

大功告成. 但是这里的面条代码的问题是显而易见的:

1. 可以预见 `创建 Topic` 是一个会被反复调用的方法(such as CLI), 写在 view 中将难以复用代码.
2. 返回的 JSON 硬编码构造 dict, 可以预见这也是一个会被反复调用的方法(such as GET API).
3. Authentication 与 Authorization 的代码也是可以预见会被大量复用.

注意我们在这里仅仅是使用了 DRY 原则, 这是入门程序员的第一门课, 相信大家都身经百战了.
所以看起来都是只是 `封装` 就能解决的问题, 我们撸起袖子很容易就能撸出下面的代码:

```python
# models.py

class BaseModelManager(models.Manager):
    def get_or_none(self, **kwargs):
        try:
            return self.get(**kwargs)
        except ObjectDoesNotExist:
            return None

    def get_by_id(self, id_):
        return self.get_or_none(pk=id_)

class Jsonizable:
    JSONIZABLE_FIELDS = None
    
    def to_dict(self) -> dict:
        rv = {}
        for field in self.JSONIZABLE_FIELDS:
            ...
        return rv

class BaseModel(Model, Jsonizable):
    objects = BaseModelManager()

    class Meta:
        abstract = True

class Topic(BaseModel):
    id = models.AutoField()

    JSONIZABLE_FIELDS = ('id', 'rounds')

    @classmethod
    def create_all(self, topic_info: dict) -> 'Topic':
        for round_info in topic_info['rounds']:
            ...
        return topic

# views.py

class TopicIndexView(ApiView):
    @decode_json_body(allowed_fields=('product_id', 'rounds'))
    def post(self, request):
        request.account.validate(request.json['product_id'])
        topic = Topic.create_all(request.json['topic'])
        return JsonResponse(topic.json())#

# middleware.py

def get_account(view_func):
    def middleware(request):
        request.account = ...
        return view_func(request)
    return middleware

# utils.py

def decode_json_body(*, allowed_fields, required_fields):
    def wrapper(view_func):
        ...
    return wrapper

class ApiView(View):
    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(...)
        except ApiError as e:
            return ...
```

用了一些 Django 的 hook 让代码比较工整, 我详细列举一下:

1. 使用 middleware `get_account` 做Authentication 返回 401
2. 使用 decorator `decode_json_body` 做简单的 request validation 返回 400 / 412
3. 使用 `ApiView` 基类做异常捕捉 / 日志 / 4XX 返回
4. 使用 `BaseModel` 基类实现 `to_json` 方法等
5. 组装 Topic 的工作作为 Topic 的一个方法 `create_all`

一位对 Python 代码稍微有点追求的程序员可能就沾沾自喜止步于此了, 但是我必须指出, 就算代码风格看上去还行, 但是设计上的缺陷为以后的扩展埋下了坑:

1. 组装 Topic / Round / Question / Answer 的工作是  Topic 模型的指责吗?
2.  `create_all` 中仔细校验了请求过来的数据结构, 比如字段缺失 /  错误类型,  那么校验工作是组装方法的职责吗?
3. `to_json` 太泛化, 我们决定提供参数 `fields` 供调用方指定 `to_json` 返回的结构, 那么翻译业务层的数据结构是模型的职责吗?

我们在这里用单一职责原则 argue, 但是单一职责原则(SRP)是一个说起来容易做起来难的事情,  我们不妨换个说法, 开放封闭原则,  才是衡量软件设计好坏的指标.

组装复杂业务数据结构, 我们引入 DDD 术语 `聚合(Aggregate)`, 它的顶级模型叫做`聚合根`.

在上面的代码中, 我们让把创建聚合的任务交给了聚合根, 但是考虑以下场景:

1.  随着业务需求变化, 我们要全面升级 Round 模型及其 Cascade, 我们的策略是创建全新的 RoundV2 / QuestionV2 / AnswerV2, 同时在一段时间内保持双写两个版本的模型, 那么这时候只能增加一个 `Topic.create_all_v2`, 然后是 `create_all_v3`, 失控感..
2. 随着业务负载增加, 我们决定弃用外键, 完全让应用层自己进行 ID 查询, 那么这时候模型之间其实是完全解耦的状态, 讲道理他们之间只需要知道彼此的 interface 就够了, 根本不应该知道具体类, 否则硬编码一处修改全家火葬场.
3. 随着业务逻辑越来越复杂, 我们决定分拆服务, 把语料模型与产品模型(就是之前进行 Authorization 动不动就返回 403 的那个逻辑)分拆为两个服务,   我们发现语料模型做不了 validation 了,因为validation 是产品模型才能做的事情(校验产品 ID), 而语料模型现在在另一个服务里了.
4. 随着业务越来复杂, 我们有相似逻辑的 API, 但是对于返回的字段有微小的差别, 一个`to_json` 被传入各种参数, 用起来难受, 代码越来越面条.

我想我们已经有足够的理由把组装聚合的工作扔出去了.

第一个问题, 组装聚合是谁的职责?

工厂!

没错, 就是 GoF 里的那个工厂, 就是有工厂方法的那个抽象工厂.
使用了工厂的好处是显而易见的,  抛开 GoF 微观视角, 在整个代码的组织上完成了高度的解耦, 但是又非常好扩展.

```python
class TopicFactory:
    def get_round_cls(self):
        return Round

    def get_question_cls(self):
        return Question

    def new(self, topic_info: dict):
        round_cls = self.get_round_cls()
        for round_info in topic_info['rounds']:
            round_cls.object.new()
            ...
```

工厂的好处在这里一目了然:

1. 内聚. Factory 指定 TopicV2 必须和 RoundV2 / QuestionV2 / etc. 一起工作,  它不可能和 QuestionV3 模型一起创建.
2.  解耦.   在之前模型与模型间相互硬编码具体类, 而现在模型间依赖接口, 所有的具体类全部由工厂指明, 非常松耦合.
3. 开放. 工厂方法 `get_round_cls` / ... 只要通过继承就能修改, 在假定接口一致的情况下, `new` 方法都不需要修改, 这是 `template` 模式的绝佳应用.
4. 封闭. 由于是高度内聚, 当然封闭.

但是现实情况会更复杂一些, 我还是要解释一下:

1. 上面的示例代码是基于静态语言, 也就是 GoF 的写法, 在动态语言 Python 中, 我们大可放心大胆使用类变量.( 澄清, 其实是 Smalltalk 的写法, Java 不能返回一个 class, 额好像 reflect 可以, 好吧)
2. 如果没有多态多版本的需求, 其实做如此重量级的抽象工厂实在没啥必要, 所以在产品原型阶段, 我们先在是聚合根中实现类方法 `create_all` 中也不是不可以. 一句话, 不要教条.

第二个问题, 校验工作是谁的职责?

值对象!

好吧又是一个 DDD 的术语, 值对象(Value Object) 对应的概念叫做实体(Entity), 他们的核心区别是:

1. 值对象不可变, 实体可变.
2. 值对象无 ID, 实体有 ID.
3. ...

假如我们拥有值对象 `TopicInfo` / `RoundInfo` / `QuestionInfo` / ..., 那么代码可能会是这样:

```python
# views.py

class TopicIndexView(ApiView):
    def post(self, request):
        payload = request.json
        topic_info  = TopicInfo(payload['topic'], account=request.account)
        topic = TopicFactory(version=2).create(topic_info)
        return JsonResponse(topic.json())
```

我们看到校验的工作, 包括两个部分, 数据结构和权限校验( 检查 account_id 是否与登陆 account 一致) , 现在全部由一个 TopicInfo 对象承担, 非常干净.
 那么值对象的最佳实践, 在 3.7+ 毫无疑问是 `dataclass()`, 3.7- 用 collections.namedtuple  或者 typing.NamedTuple, 非常顺畅.



第三个问题, 业务层数据结构是谁负责翻译?

 表现层模型(PresentationModel)!

或者又叫做 ViewModel, 都行.

就是说我们单独定义一个表现层,  用来和领域模型解耦, 它不一定和领域模型的结构一致, 但是它一定表达的是业务逻辑里的数据结构, 也就是用户上传和我们返回的数据结构.

```python
class ViewTopic:
    @classmethod
    def build(cls, topic: Topic) -> 'ViewTopic':
        visitor = ViewTopicVisitor()
        topic.accept(visitor)
        return cls(visitor.get_result())

class ViewTopicVisitor:
    def visit(self, topic: Topic):
        self._res['topic_id'] = topic.id
        self._res['topic_headline'] = topic.headline

class Topic(BaseModel):
    ...

    def accept(self, visitor):
        visitor.visit(self)
        for round in self.rounds.all():
            round.accept(visitor)
```

这一系列眼花缭乱的方法又必要进行一些说明:

1.  视图函数只调用 ViewTopic而不接触 Topic,  实现业务与领域模型的解耦, 这是很重要的, 可能你现在觉得不重要, 甚至会觉得 Restless 这种完全暴露模型的透明服务才是王道, 错误!
2. ViewTopic 使用一个 visitor 进行数据收集, 这是经典的 visitor 模式!  其中古怪的 visit 方法和 accept 是基于这样的考虑: visitor 对 visitee(模型们) 的内部结构一无所知, 只假定能够从最简单的接口取出数据; 内部结构依然是模型自己的内部黑箱, 由 accept 方法告诉 visitor, "这是一个 round, 给". 这里解决的最重要的问题是, 完成了模型内部结构与 visitor 的解耦.
3. visitor 的好处很多, 比如利用双分派 (double-dispatch)  或者调停者模式(mediator)能够让代码非常干净, 但是它的弊病是如果 visitee 的类型经常新增, 就需要把所有 visitor 进行修改, 这一点上对修改不封闭, 所以要自己评估场景.
4. 一个纯正的 ViewModelVisitor 应该连领域模型都摸不到, 而是直接暴露接口 `inform_topic_id` / `inform_topic_headline`, 这些字段全部在模型 accept 方法里内部黑箱操作了, 才完全解耦了visitor 和 model.

有了如此的 ViewModel 之后, 我们的领域模型和业务逻辑已经完全解耦:

1.  用户请求由值对象+工厂完成了表现层模型到领域模型转换
2.  返回用户的响应由 visitor 完成了领域模型到表现层模型的转换

那么这就很自由自在了.

在进入到更多业务逻辑的讨论之前, 我再提一嘴 RESTful API 的设计问题.

我们在这里实现了 `POST /api/v1/topics/`, 顺理成章应该实现 `GET /api/v1/topics/` 和 `GET /api/v1/topics/:id`, 现在问题来了,  我们应该依次实现关联对象的 API 吗, 也就是 `GET /api/v1/topics/:id/rounds/:id/questions/:id` 诸如此类的东西.

如果只是从 REST 的角度去看, 很合理, 很实用, 很完备, 要实现.

但是从 DDD 的角度来看, 不行.

API 不是什么资源都能暴露的, 在业务场景下, 它只能暴露聚合根. 聚合最重要的因素是: 在一致性边界之内.  如果暴露子对象的资源, 无疑损害了聚合的原子性, 给自己加需求不说, 一致性的保障也有问题.

说了这么多, 这只是开始的开始, Welcome to the real world!  

## 二. Business

我们开始有了更多复杂的业务需求.

我们决定为数据库里的语料提供模糊搜索的功能, 但是大家一致决定坚决不用 MySQL LIKE 搜索,  需要扩展的时候全家火葬场,  而 ElasticSearch 是不错的选择.

那么问题来了, 我们如何进行数据的同步?

也就是说我们通过 RESTful API CRUD 了数据, 对应的 ES 上的数据也要修改, 我们怎么做?

这里不谈最终一致性的问题, 这里讨论的是代码组织的问题: 这个逻辑放在哪个地方最合适?

1. 最幼齿的方式, 写个 `topic.sync_es()` 方法, 每次在 view 函数中创建完成后手动调用一下.
2. 使用 signal  实现 hook, 在 signal handler 中做同步.

乍一看 signal 高端, Django ORM 内置 hook, 修改模型自动触发, 省去了每次必须手动调用的心智负担, 简直棒极了.

但是有这么几个问题:

1. 如何触发关联对象的 signal handler?
2. 如何实现 batch operation?
3. 如何在 handler 中同时获取到修改前的模型与修改后的模型

第一件事是说, 比如我们有这样的代码:

```python
from django.db.models.signals import post_save

class Topic:
    
    def on_create(sender, instance, *args, **kws):
        ...

class Round:
    def on_create(sender, instance, *args, **kws):
        ...

post_save.connect(Topic.on_create, sender=Topic)
post_save.connect(Round.on_create, sender=Round)
```

要注意我们必须实现的是, 只修改了 Round 对象, 但是必须触发其关联的对象 Topic 的 `on_create` 方法; 类似的, Round 关联的 Question / Answer 也都必须级联触发, 这个工作职能自己手动实现.
但是这样很糟糕, 如果我们手动实现了所有 signal handler 的级联触发, 我们在 `工厂` 那里做的一切解耦都无用了: 模型之间的具体类又硬编码耦合起来了.

第二件事是说, 考虑一下我们的 `Topic.object.filter(...).delete()` 这个操作.

两个问题:

1. filter 返回的 QuerySet 的 delete 方法不会触发 signal handler.
2. 就算我们能通过 override QuerySet 的 delete 方法强制它触发 signal, 我们将在一次 delete 操作里触发成千上万次的 DELETE 同步调用, 因为 signal 不是 batch 操作!

ok, 我们依然有办法去做, 比如实现一套 TCP 延迟发送算法, 等待 500ms 并收集这期间的所有请求最后一起发出去, 当然也能做, 但是我们要用 threading.Timer / Queue 等等线程工具了, 倒也不是问题, 但是感觉有点太复杂了: 我们只是想同步一下 CRUD 而已!

 第三件事是说, signal 的 `post_save` / `pre_save` 等等所有的 handler, 无论如何查阅文档都找不到一个接口能够同时获取修改前与修改后的模型:

```python
def post_save_handler(sender, instance, old_instance, ...):
    pass

post_save.connect(...)

```

这不是一个过分的需求, 考虑一下我们需要做细致的 diff 并且只是增量地发请求去同步, 这对于大型聚合来说是必须的: PATCH 操作, 但是 Django signal 做不到!

那么我们应该怎么做?

服务层( Service Layer) + 观察者模式(Observer)!

服务层是 DDD 里非常重要的一个概念, 因为在经典的 MVC 框架中我们并没有这个概念, 但是我经常有这样的想法:

1. 卧槽, 这个 view 函数里的逻辑我想复用该怎么办, 继承 + 模板方法吗, 不合适吧, 为了 DRY 而破坏了组件职责, 这不就是标准的过程式代码面条吗?
2. 卧槽, 我这个 CLI 函数也要复用, 简直没地方抽出来啊; 我是说我当然可以抽出来作为一个函数然后让大家去调用, 但是这个函数也太奇怪了吧, 它是什么职责, 它应该在哪个模块?
3. 卧槽, 这个 view 里的业务逻辑也太丧心病狂了吧, 越加越多; 但是放到 Model 里作为一个方法好像也不太合适, 因为涉及多个模型之间的交互: 先查询模型 A, 再根据结果去模型 B 做点事情, 好像就应该放到 view 里, 但是好像又有点失控了.

不用犹豫, 我们需要一个全新的代码层: 服务层.

DDD 对服务层的定义中最关键的几点是:

1.  服务层是模型的客户,  服务层调用模型
2. 应用层( aka  视图函数) 是服务层的客户, 应用层调用服务层
3. 服务层处理业务逻辑, 应用层表达用户故事

比方说我们习惯这样的代码:

```python
def put(request, id_):
    try:
        topic = Topic.objects.create(pk=id_)
    except ObjectNotFound:
        raise HTTPNotFound()
    topic_value = TopicValue.from_requset(request) # validation
    topic_factory = TopicFactory.instance() # factory
    topic = topic_factory.new(topic_value) # create aggregate
    view_topic = ViewTopic(topic) # presentation model
    return view_topic.json()
```

 没毛病, 但是如果按照 DDD 的要求, 我们应该在 view 里面表达 user story:

```python
def put(request, id_):
    topic = update_topic(id_, request.json)
    return ViewTopic(topic).json()
```

而在 `update_topic` 里再包含奇怪又复杂又容易新增需求的业务逻辑.

那么这和最开始的 sync ES 的需求有什么关系?

我们打算在服务层做这个事情, 不过需要依赖 Observer 模式.

简单来说, 代码是这样的:

```python
class TopicService:
    def update(id_, topic_info):
        ...
        publisher = DomainEventPublisher()
        publisher.sub(TopicCreateEvent, Topic.on_create)
        ...
        return topic

class Topic:
    def create(cls, ...):
        ...
        publisher = DomainEventPublisher()
        publisher.pub(TopicCreateEvent(topic))
```

我们通过在服务层订阅事件与回调, 在模型层发布事件来处理这件事, 那么非常灵活了, 因为我们按照我们喜欢的方式创建事件对象:

1. 聚合内的所有模型都发布 TopicUpdateEvent, 解决了级联触发的问题.
2. delete 的时候发布 TopicDeleteEvent, 并在事件中声明删除条件, batch 操作不再僵硬.
3.  同时获得修改前后的对象, 构造进入 TopicUpdateEvent  中就可以了.


不仅如此, 它还带来了更多的好处.

假设在未来我们的需求又增加了, 之前是只要 Topic 变更就同步, 但是由于奇怪的需求, 我们要求指定的 Product 就不要同步, Topic  聚合根与 Product 通过 product_id 关联.

简单直白的代码是这样的:

```python
class Topic:
    def on_create(sender, instance, *args, **kws):
        if Product.objects.get(pk=instance.product_id).type == 'third_party':
            return
        ...

post_save.connect(Topic.on_create, sender=Topic)
```

好的, 直接把逻辑加入了 signal handler 中, 简单, 一小时内上线.

但是问题是, 随着逻辑越来越复杂, 我们开始在 signal handler 里加入了大量的业务逻辑, 以后这里面的代码简直就是乱七八糟的面条, 充斥了不同领域的模型, smelly.

如果我们使用了发布领域事件再使用订阅机制去做, 就一点都不僵硬了:

```python
class Topic
    def on_create(sender, instance, *args, **kws):
        publisher = DomainEventPublisher()
        publisher.pub(TopicCreateEvent(topic))

class TopicService:
    def update(*args, **kws):
        def on_update(topic):
            if sync(Product.objects.get(pk=topic.product_id)):
                sync()
        publisher.sub(TopicUpdateEvent, on_update)
```

会发现模型内部的状态非常干净, 只表达自己模型的行为, 对于与其他模型的交互, 要么通过接口, 要么发布领域事件, 肮脏的业务代码全部让服务层做, 反而更加容易复用.

最后再说两个东西.

第一个是上面那个 `sync` 函数用来判断一个 Product 是否应该应该同步语料到 ES, 这件事正确的做法是, (首先假设 Product 是另一个领域的模型, 我们已经分拆出了微服务, 通过 RESTful API 获取), 使用防腐层( Anti-Corruption Layer).

防腐层的职责是隔离本地模型与远端模型, 并且把远端模型翻译成一个本地的内存模型(值对象! Value Object), 这个本地的内存模型包含了本地需要的方法 / 属性数据.

比如对于这里的例子来说:

```python
class LocalProduct:
    id: int
    ...

    @classmethod
    def from_product(cls, product: dict):
        self.id = product['id']
        ...

    @classmethod
    def get(cls, id):
        product_model = product_service.get().json()
        return cls(product_model)
        
    def should_sync_topic(self):
        ...
```

注意在远端的 Product 领域中并没有 `should_sync_topic` 方法, 我们是在把另外一个领域模型翻译成本地对象的时候加入了业务逻辑, 这让 Product 领域的代码更加内聚, 否则你在 Product 领域模型里写了一大堆只有 Topic 领域需要的业务逻辑就太烂了.


第二件事是依赖注入与控制反转, 在 DDD 中提倡连 ORM 都不要暴露, 只能暴露 Repository, 我们来看一下这是什么意思.

```python
# models.py

class TopicRepository:
    @classmethod
    def init(cls, impl):
        self._impl = impl

    def get(self, *args, **kws) -> Topic:
        return self._impl.get(*args, **kws)

    def create(self, *args, **kws) -> None:
        self._impl.create( *args, **kws)
```

基本什么都没干, 就是声明了接口, 然后把调用都 delegate 给了具体的实现类.

然后假设我们用关系型数据库 +  ORM 作为这个模型的存储, 那么有:

```python
# infra/orm.py

class TopicRepoORMImplement:
    def get(...):
        self.objects.get(...)

    ...
```

然后假设我们用 ES 同步也用 DSL 建模:

```python
# infra/es.py

class TopicRepoESImplement:
    def get(...):
        self.es.get(...)
```

然后假设我们用 MongoDB 作为底层:

```python
# infra/mongo.py

class TopicRepoMongoImplement:
    def get(...):
        self.mongo.some_method()
```

然后我们只要在用之前(比如应用初始化的时候通过配置项实例化对应的实现就可以了:


```python
# apps.py

class DefaultApp:
    def ready(self);
        TopicRepository.init(settings.REPO_CONFIG)
```

这样我们只需要调用接口就能获取数据, 至于接口之下的实现是 MySQL / ES / MongoDB / HBase / ... 都不重要.

好处是显而易见的. 我见过无数的滥用 ORM 的代码, 在视图函数里各种扭曲的方式用着高级的查询, 处理异常, 都是不好的. 不想说太多, 自己体会吧.

至于为什么这叫做 `控制反转`(依赖注入只是控制反转的最经典的实现), 因为你会发现模型层的类 `TopicRepository` 居然被基础设施层 `infra/es.py` / `infra/orm.py` / `infra/mongo.py` 所依赖, 我上面偷懒没写全, 实际上所有的 Implement 应该都继承模型层的 TopicRepository, 表达出`我实现了你的所有接口`.

你可能还没理解这里的玄机.

在普通的代码中, 应用层 -> 服务层 -> 模型层 -> 基础设施层, 每一级的分隔非常清晰, 你不会看到基础设施层(比如说 Django ORM 的代码里)看到从模型层导入什么类, 这是标准的分层架构.

但是控制反转完全颠覆了, 模型层声明接口, 基础设施层导入模型层的接口, 实现具体方法, 再通过依赖注入的方式初始化, 就很棒.

要记住:

```
高层模块不应该依赖低层模块，二者都应该依赖其抽象；抽象不应该依赖细节；细节应该依赖抽象。
```


 
不想写了, 就这样吧, 工作的代码都没写完..
