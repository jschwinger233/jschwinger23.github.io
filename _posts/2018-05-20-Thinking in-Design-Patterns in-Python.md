---
layout: post
---

> WARNING: 这篇日志的代码基本都不可运行。

我想写一个 NLP 训练器的框架，输入语料，输出模型。

```python
class TrainingJob:
    def __init__(self, input_config, output_config):
        self.input_config = input_config
        self.output_config = output_config

    def run(self):
        corpus = self.download_corpus()
        model = self.train(corpus)
        self.upload_model(model)

    def download_corpus(self):
        # do things

    def train(self, corpus):
        # do things

    def upload_model(self, model):
        # do things


input_config = {...}
output_config = {...}
training_job = TrainingJob(input_config, output_config)
training_job.run()
```

大致这样吧，再简化就看不下去了。
应该还是比较清晰明了的，就是输入配置、下载语料、训练模型、上传模型，四个步骤。

但是很快我们发现我们有各种奇怪的训练器，大家的训练算法千奇百怪，需要实现不同的 `train` 方法，很自然的，我把 `train` 定义为抽象方法，由子类去实现：

```python
class TrainingJob(abc.abc.ABC):
    ...

    @abc.abstractmethod
    def train(self, corpus):
        pass


class RockTrainingJob(TrainingJob):
    
    def train(self, corpus):
        # do rock things


class BluesTrainingJob(TrainingJob):
    
    def train(self, corpus):
        # do blues things


input_config = {...}
output_config = {...}
rock_training_job = RockTrainingJob(input_config, output_config)
rock_training_job.run()
```

好的，这么一个幼齿的实现已经是 `Template Method` (GoF P306) 了。
`Template Method` 的目的是 `Define the skeleton of an algorithm in an operation, deferring somesteps to subclasses`，我们的场景应该是完美切合模式的。

---

Let's think more.

考虑给这个框架加一个 entrypoint 能够直接从命令行调用，大概长这样：

```
training-job -k rock -i '...' -o '...'
```

然后这个命令行做的事情是使用 `RockTrainingJob` 传入 `-i` 参数作为 `input_config`、`-o` 参数作为 `output_config` 进行训练。

这里的重点是如何通过 `-k` 指定的参数使用不同的 `TrainingJob`。


```python
@click.option('-k', '--klass')
@click.option('-i', '--input-config')
@click.option('-o', '--output-config')
def main(klass, input_config, output_config):
    training_job_class = get_training_class(klass)
    training_job = training_job_class(input_config, output_config)
    training_job.run()
```

注意这里是 `get_training_class` 其实是动态语言+类作为一等公民 (first class) 的 shortcut，在大部分静态语言中由于无法返回一个 class，因此需要格外强调工厂方法：`we call a factory method because it's responsible for "manufacturing" an object` (GoF P122)。

如果 Python 无法返回一个 class 是话，那么实现一个工厂函数是必要是：

```python
class TrainingFactory(abc.ABC):

    def get_training_job(self, *args, **kws):
        return self.get_training_class(*args, **kws)

    @property
    @abc.abstractmethod
    def get_training_class(self):
        pass


class BluesTrainingFactory(TrainingFactory):
    def get_training_class(self):
        return BluesTrainingJob


class RockTrainingFactory(TrainingFactory):
    def get_training_class(self):
        return RockTrainingJob


training_factory = get_training_factory(klass)
training_job = training_factory.get_training_job(input_config, output_config)
training_job.run()
```

你看 `Factory Method` (GoF P121) 里令人讨厌的 `Creator` 抽象类和具体类就这样出现了。
[图]
`TrainingFactory` 就是 `Creator`，`BluesTrainingJob` 和 `RockTrainingJob` 是 `ConcreteCreator`，`get_training_job` 是 `factory method`。

这里的实现展示了 GoF 中的 Implementation Issues 3 中描述的 Smalltalk：`Smalltalk programs often use a method that returns the class of the object to be instantiated`，这里让 Python 照葫芦实现了一下。

`get_training_factory` 其实对应的是 GoF Implementation Issues 2 中的 `Parameterized factory methods`。至于 `get_training_class` 应该如何实现，手动 register 是比较好的，虽然你用 `locals()` 也没问题。

在 `Parameterized factory methods` 的实现里有个陷阱，考虑如下的实现：

```python
class TrainingJob(abc.ABC):
    def __new__(cls, klass):
        for concrete_class in cls.__subclasses__():
            if concrete_class.__name__ == klass:
                return concrete_class.__new__()
        raise ValueError


class RockTrainingJob(TrainingJob):
    ...


class BluesTrainingJob(TrainingJob):
    ...
```

在这个实现里，我们把 `get_training_job` 函数做的事实现到了 `TrainingJob.__new__` 里，乍一看我们因此获得了能力可以通过 `__subclasses__` 特殊方法去搜索具体类，但是有几个问题：

1. `__new__` 被递归调用啦，简直惨不忍睹。
2. `__new__` 返回是对象不是 `cls` 的实例就不会调用 `__init__` 方法
3. `__new__` 的设计目的是订制不可变对象的创建，把 `__new__` 作为工厂方法是滥用

所以我们发现在 Python 中实现 `Factory Method` 还是简单清爽地 `get_training_class` 就好了，非常干净。

---

Let's think more.

现在我们把 `TrainingJob` 这个仓库整体作为一个 training-framework-lib，然后分别实现 rock-training-lib 和 blues-training-lib。

让我说得更具体一点。

training-framework-lib 里实现了 `TrainingJob` 抽象基类和 `training-lib` CLI；通过在此基础上实现 rock-training-lib，最后通过 `pip install` 的方式安装 rock-training-lib、再直接调用 `training-lib` CLI 使用 rock-training-lib 中订制的算法。

如果你没意识到这件事情和之前有什么重大不同的话，我提醒一下，之前的 `Template Method` 和 `Factory Method` 模式，最终我们都是实例化了一个特定的子类、调用子类的 `run`、从而使用子类特定实现的方法去做事；但是现在我们是要求实例化父类、调用父类的 `run`、却依然使用子类的特定实现。

好的，我们进入到控制反转的领域了。

控制反转是一个伟大的概念，几乎所有的框架都离不开控制反转。Django 到 MVC 到简单的 `conf.settings` 里无处不在体现控制反转。

控制反转不仅是代码微观层的重要设计模式，同时也是宏观层的重要方法论。在 DDD 中无处不强调的依赖倒置原则“高层次的模块不应该依赖于低层次的模块，他们都应该依赖于抽象；抽象不应该依赖于具体实现，具体实现应该依赖于抽象”，其思想都是通过控制反转的方式为高层模块提供底层服务。

在这里我们使用控制反转最精炼的实现：依赖注入。

按照 Martin Fowler 那篇首次提出 DI 概念的文章中 (`Inversion of Control Containers and the Dependency Injection pattern`)，我们使用 Constructor Injection.

```python
class Trainer(abc.ABC):
    @abc.abstractmethod
    def train(self, corpus):
        pass


class TrainingJob(abc.ABC):
    
    @classmethod
    def init_instance(cls, trainer: Trainer):
        cls._instance = cls(trainer)

    @classmethod
    def get_instance(cls):
        return cls._instance
    
    def __init__(self, trainer: Trainer):
        self.trainer = trainer

    def run(self, input_config, output_config):
        corpus = self.download_corpus(input_config)
        model = self.trainer.train(corpus)
        self.upload_model(model)

    ...
```

在框架级别上，我们抽象出 `Trainer` 抽象基类，并且要求实例化 `TrainingJob` 的时候传入 trainer 具体类的实例。

然后在子类的仓库中我们需要在模块初始化之际就使用特定实现的 `RockTrainer` 去实例化 `TrainingJob`。

```python
class RockTrainer(Trainer):
    def train(self, corpus):
        # rock


TrainingJob.init_instance(RockTrainer())
```

这样在稍后调用框架里的 CLI 时，直接调用 `get_instance` 方法就能在父类中使用子类订制的 `RockTrainer` 了。

```python
def main(...):
    training_job = TrainingJob.get_instance()
    training_job.run(...)
```

稍微熟悉 GoF 的同学都会注意到，上面的依赖注入，感觉和 `Strategy` 好像啊。

`Strategy` 是做啥的？

> Define a family of algorithms, encapsulate each one, and make theminterchangeable. Strategy lets the algorithm vary independently fromclients that use it.

[图]

不错，依赖注入确实很像 Strategy 模式。Strategy 的目的是为了能够更加动态切换内部一个组件的实现，但是这恰好也实现了依赖注入，让我们可以直接从父类调用子类的实现。

---

Let's think more.

在 Martin Fowler 那篇介绍 DI 的旷世杰作里，还提到了另一个 DI 的方法叫做 Service Locatar，其实也很有趣。

如果你熟悉 `好莱坞风格` 的话，你一定不会对此感到陌生。

所谓好莱坞风格，就是 `Dont't call me,I will call you`，这里的 call 有打电话和调用的双关。一种典型实现就是，注册，疯狂注册，注册到你怀疑人生。

首先在框架实现 `ServiceLoader` 提供注册机制：

```python
class ServiceLoader:
    
    def __init__(self):
        self._registry = {}

    def __call__(self, type_):
        def decorator(cls):
            self._registry[type_] = cls
            return cls
        return decorator

    def get(self, type_):
        return self._registry[type_]


service_loader = ServiceLoader()
```

然后在子类仓库中注册子类：

```python
@service_loader('trainer')
class RockTrainer:
    ...
```

最后在框架的 `TrainingJob` 基类中使用 ServiceLoader 获取 Trainer 就可以了：

```python
class TrainingJob:
    def run(self, ...):
        trainer = service_loader.get('trainer')
        trainer.train(...)
```

但是如果你和我一样对注册嗤之以鼻的话（因为我认为继承就已经是很 explicit 的关系了，有继承就不应该有注册，除非继承太泛化），那么可以使用 `__init_subclass__` 或者元类在继承之时做好注册。但是本质思想都是一样的。


---

就这样吧- -
虽然还有很多模式可以说，但是感觉最重要的还是创建型的这几个和控制反转的思想。
表达能力极差，实在做不到娓娓道来庖丁解牛。
说实话就算我有 DI 的思想，我也完全写不出 Martin Fowler 那样深入浅出的文章。
软技能太渣了。。
