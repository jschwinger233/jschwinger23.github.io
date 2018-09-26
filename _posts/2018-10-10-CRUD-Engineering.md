---
layout: post
---

发现大家普遍对业务代码充满不屑, 张口 `CURD 低级`, 闭口 `业务代码恶心`, 但是不巧的是我对 CURD 有着截然不同的看法, 我觉得这件事非常高级, 高级到不是一般的程序员能够做得好的.

全文使用 Django, 因为我最熟悉.


---
## 一. 模型与 RESTful

我们要做一个语料管理系统, 经过与算法团队和产品经理团队的讨论, 大家拍板了以下的模型关系:

用人类的话说, 一个话题 (Topic) 包含多轮 (Round) 问答, 一轮问答包含多个问题 (Question) 和一个回答 (Answer).

现在要提供一些初步的 CURD API, 嗯.

那么第一个问题, 怎么实现一个完整的新增 API.

### 1.1 POST `/api/v1/topics/`

好了我直接把这个幼齿的 API 写出来了, 那么先来个反面教程吧:

```python
class Topic(db.Model):
    id = db.AutoField()

class Round(db.Model):
    id = db.AutoField()
    topic = db.ForeignField(Topic, on_delete=cascade, related_name='rounds')

class Question(db.Model):
    id = db.AutoField()
    content = db.TextField()
    round = db.ForeignField(Round, on_delete=cascade, reelated_name='questions')

class Answer(db.Model):
    id = db.AutoField()
    content = db.TextField()
    round = db.OneToOneField(Round, on_delete=cascade, related_name='answer')

def create_topic_view(request):
    topic_info = json.loads(request.content)
    topic = Topic.objects.create()
    for round_info in topic_info['rounds']:
        round = topic.rounds.create()
	for question_info in round_info['questions']:
	    round.questions.create(**question_info)
	Answer.objects.create(round=round, **round_info['answer'])
    return JsonResponse({'id': topic.id, 'rounds': [{'questions': [{'id': question.id, 'content': question.content} for question in round.questions.all()], 'answer': {'id': round.answer.id, 'content': round.answer.content}} for round in topic.rounds})
```

大功告成.

但是这里的问题是:

1. 可以预见 `创建 Topic` 是一个会被反复调用的方法, 写在 view 中将难以复用代码.
2. 没有数据校验, 如果客户端上传不符合约定的数据结构导致服务器直接 500.
3. 返回的 JSON 硬编码构造 dict, 可以预见在 GET 请求中也一定会调用相同的方法.

看起来都是只是 `封装` 就能解决的问题, 我们可以利用装饰器做一个简单的字段校验, 把创建组合对象的逻辑作为 Topic 的一个类方法, 在创建时候做好数据校验, 再用 Mixin 或者定制化的 ObjectManager 提供 Jsonize 的功能. 最后代码长得像这样:

一位对 Python 代码稍微有点追求的程序员可能就沾沾自喜止步于此了, 但是我必须指出, 就算代码风格看上去还行, 但是设计上的缺陷为以后的扩展埋下了坑:

1. 组装 Topic / Round / Question / Answer 的工作是 Topic 的指责吗?
2. 校验工作是组装方法的职责吗? 考虑一个有复杂校验规则的场景, 比如我们定制了一套 DSL 可供上传的语料使用, 那么这里的校验放在组装的 `create_all` 方法里真的大丈夫?
3. 服务返回数据与模型序列化方法耦合太紧. 考虑一下如果我们提供 `/api/v1/internal/` 和 `/api/v1/external/` 作为 prefix 的 API, 分别包含元信息字段(`updated_at`)和只包含标识符字段(`id`), 那么上面的代码会很难修改.

为什么要在意职责? 这不仅是语意上的问题, 更加关系到开放封闭原则, 影响到未来的扩展.

考虑一下

毫无疑问组装工作不应该是 Topic 的工作, 只要你看看其他的 class 有没有组装的
