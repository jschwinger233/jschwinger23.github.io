---
layout: post
---

> For my ex whose WeChat name was TurtleShell(乌龟壳).

上一篇[文章](https://jschwinger23.github.io/2018/02/23/Ghost-in-the-Shell.html)是按照`解决问题(Cookbook)`的方式来组织文章结构, 这篇文章将采用`技术细节(Guide)`的方式来组织.

老规矩:

```
$ bash --version
GNU bash, version 3.2.57(1)-release (x86_64-apple-darwin17)
Copyright (C) 2007 Free Software Foundation, Inc.
```

BTW, bash 上个月已经进化到 5.0, 少年们要不要来一发.

---

# **1. Command Substitution**

相信大家一定非常熟悉了, 两个形式:

1. \``cmd`\`, 但是 backquotes 的问题是不能嵌套, 所以我之前都用另一种形式.
2. `$(cmd)`, 虽然可以嵌套, 但是也有一些其他问题, 所以我现在尽量用 Process Substitution.

#### **1.1 比方说**

我们第一次 git push 一个新的 remote 分支的时候总是需要完整输入分支名字:

```
git push -u origin <branch-name>
```

使用 Command Substitution 我们可以避免手动输入:

```
git push -u origin $(git rev-parse --abbrev-ref HEAD)
```

又比如, 使用 [pyenv](https://github.com/pyenv/pyenv) 的时候偶尔需要查看源文件, 那么:

```
vi $(pyenv which ipython)
```

就可以查看 IPython 的 entrypoint 源码.

或者我们要遍历一个文件的每一行, 如果每一行的数据里没有空格, 那么可以简单地来:

```
for line in $(cat file.txt); do echo "-> $line"; done
```

#### **1.2 坑**

然而坑是非常多的!

**1.2.1 `\0` 会被移除!**

简直可以说是日了狗了.

比如说我们要处理 `find -print0` 的结果:

```
(IFS=$'\0' && for file in $(find . -name '*.md' -print0); do echo "-> $file"; done)
```

是不 work 的, 输出的结果所有的文件在一行被打印出来, `IFS=$'\0'` 设置没有问题, 问题是出在 `$(find)` 输出的结果把 `\0` 删掉了..

```
# bash 的坑很多, 为了证明是 Command Substitution 的锅而不是 IFS 和 echo 的锅, 我运行了下面三行代码:

# 首先证明 `echo` 能够打印 `\0` 的 IFS: 
(IFS=$'\0' && od -a <(echo $IFS))
# output: 0000000   nl

# 再证明 echo Command Substitution 吃掉了 `\0` 
od -a <(echo $(find . -name '*.md' -print0))
# output: 0000000    .   /   b   .   m   d   .   /   a   .   m   d  nl

# 最后再看 Process Substitution: 
od -a <(find . -name '*.md' -print0)
# output: 0000000    .   /   b   .   m   d nul   .   /   a   .   m   d nul

# 后者多出的那个 `nul` 说明了一切.
```

所以如果文件中没有 `\n` 的话只能:

```
(IFS=$'\n' && for file in $(find . -name '*.md'); do echo "-> $file"; done)
```

_TIPS: 我用了一对圆括号把整个命令包起来是为了使用 subshell, 这样的话修改 IFS 不会污染当前 bash._

**1.2.2 `echo` raw Command Substitution 会把 `\n` 替换为空格**

```
echo $(ls -l)
```

输出

```
total 8 -rw-r--r-- 1 whoami 1032302077 0 Feb 9 18:39 a.md -rw-r--r-- 1 whoami 1032302077 0 Feb 9 18:39 b.md -rw-r--r-- 1 whoami 1032302077 366 Feb 4 18:09 delimit.txt
```

所有结果都在一行, 可以说非常不高兴了. 

Here String 也有同样的问题:

```
while read -d $'\n' -r line; do echo "-> $line"; done <<< $(find .)
```

打印出来所有文件又在一行.

但是 Here Document 不会有问题:

```
$ while read -d $'\n' -r line; do echo "-> $line"; done <<!
> $(find .)
> !
```

每个文件都是单独打印.

所以如果使用 Command Substitution 和 echo / Here String 的时候要记得使用 partial quote:

```
echo "$(ls -l)"
while read -d $'\n' -r line; do echo "-> $line"; done <<< "$(find .)"
```

但是 partial quote 的问题是会破坏 word splitting, 也就是说不会使用 IFS 切词, 这就很痛苦了:

```
for file in "$(find .)"; do echo "-> $file"; done
```

会变成一坨打印出来就是这个原因.

妈的简直太傻逼, 加引号也不行, 不加引号也不行, 所以只要涉及到特殊字符我根本不考虑 Command Substitution, 只用 Process Substitution.

_TIPS: 我使用 `!` 而不是通常的 `EOF` 作为 Here Document 的 delimit, 其实在绝大多数情况是完全没有问题的, 能够很好节省键盘._

---

# **2. Process Substitution**

两个用法: 
1. `cmd1 <(cmd2)`, 可粗糙视为 `exec N<>$(mktemp); cmd2 >&N | cmd1 /dev/fd/N && exec N>&-`
2. `cmd1 >(cmd2)`, 可粗糙视为 `exec N<>$(mktemp); cmd2 <&N | cmd1 /dev/fd/N && exec N>&-`

那么它的好处在于:
1. 如果 `cmd1` 只接受文件名, 那么 Process Substitution 简直丝滑, 因为 `<(cmd2)` 可视为一个文件;
2. 如果 `cmd1` 接受多个参数, 那么 Process Substitution 避免了管道只能使用 `/dev/fd/0` 的捉襟见肘;
3. 如果依赖 `cmd1` 的副作用, 那么 Process Substitution 避免了管道时的 IPC;
4. 如果 `cmd2` 的结果有奇怪的字符以及 `cmd1` 依赖 `IFS` 做事情, 那么 Process Substitution 能够避免 Command Substitution 与 partial quote 的各种恶心细节.

#### **2.1 直接上栗子**

**2.1.1 只接受文件**

比如刚才的 `od` 命令, BSD od(1) 只接受文件参数而不是接受标准输入, 不过这根本不是问题, 我们可以:

```
mkfifo /tmp/fifo
find . -print0 >/tmp/fifo | od -a /tmp/fifo
rm /tmp/fifo
```

简直和吃屎没区别.

_TIPS: `find . -print0 | od -a /dev/fd/0` 是不行的, 因为 `od` 强行关闭了 `/dev/fd/0`_

所以我们用 Process Substitution:

```
od -a <(find . -print0)
```

非常干净.

再说一个我常用的, 解码系统粘贴板的 base64 数据再粘贴回粘贴板, 同时打印出来:

```
# macOS ONLY
base64 -i <(pbpaste) | tee >(pbcopy) | cat
```

**2.1.2 接受多个命令的标准输出**

再来看下使用 vimdiff 查看 git 历史版本的文件 diff, 我们可以使用 `vimdiff` 提供的 `-` 从 STDIN 读取:

```
git cat-file -p <commit1>:<filename> | vimdiff - filename
```

或者是直接使用 `/dev/fd/0`:

```
git cat-file -p <commit1>:<filename> | vimdiff /dev/fd/0 filename
```

然而如果命令强行关闭了 `/dev/fd/0` (如 `od`), 或者两个参数都是从其他命令的 STDOUT 里得到的, Process Substitution 就是唯一的选择了:

```
vimdiff <(git cat-file -p <commit1>:<filename>) <(git cat-file -p <commit2>:<filename>)
```

得到的效果不比专业 IDE 的 VCS diff 差.

又或者我们写了一个 Python 脚本, 它目前只能把 `sys.argv[1:]` 当做文件读取, 但是我们想利用管道什么的把其他命令的输出塞给它去运行, 那么不需要改一行代码, 使用 Process Substitution 就是醉猴的!

```
./script.py <(cmd1 | cmd2) <(cmd3) | cmd4
```

还有我经常使用的 `comm` 命令去重也是极其好用:

```
comm -23 <(find $DIR -type f | sort) <(git ls-tree $COMMIT --name-only -r | grep  $DIR | sort)
```

这句命令列出了 workspace `$DIR` 目录下与 `$COMMIT` 提交的 `$DIR` 目录的文件差集. 

虽然可以直接 `git diff --name-only HEAD $COMMIT | grep $DIR`, 但是表达的语义是不同的, 一个是差集, 一个 diff, 感受一下.

**2.1.3 依赖副作用**

比方说, 我要计算所有 txt 里的单词频数, 是不能用管道的:

```
find . -name '*.txt' -print0 | while read -d '' file; do 
    while read line; do 
        for word in $line; do 
            var=count_$word
            [[ -z "${!var}" ]] && eval "$var=1" || eval "(($var++))"
        done 
    done <$file 
done

for var in ${!count_*}; do echo "word ${var#count_}: ${!var}"; done
```

_TIPS: 由于 bash4- 没有 associative array, 只能使用 indirect 来模拟, 其中出现的 `${!var}` / `${!var_*}` 分别是取间接和列出所有 prefix 为 `$var` 的变量名._

这样是不行的, 因为管道里的每一个命令都 fork 了新进程, 子进程的变量赋值不会传递给父进程, 除非再处心积虑地 IPC.

所以改成 Process Substitution 就迎刃而解了:

```
while read -d '' file; do 
    while read line; do 
        for word in $line; do 
            var=count_$word
            [[ -z "${!var}" ]] && eval "$var=1" || eval "(($var++))"
        done 
    done <$file 
done < <(find . -name '*.txt' -print0)

for var in ${!count_*}; do echo "word ${var#count_} frequency: ${!var}"; done
```

_TIPS: `< <(cmd)` 看起来很奇怪, 其实把 `<(cmd)` 看成一个文件, 本质就是 block 级别的 IO redirect, like `< /dev/fd/N`._

**2.1.4 涉及特殊字符**

尤其是涉及 `\n` / `\0` 的时候, Command Substitution 的奇怪的潜规则经常让我想打人, 而 Process Substitution 保证了原汁原味的字符传递.

比方说还是要迭代 `find` 的结果, 如果文件名不含 `\n` 的话我们还可以用 Command Substitution 把 `\n` 作为 delimiter 凑合一下, 但是一旦包含的话就完全不行了, 因为 Command Substitution 会吃掉 `find -print0` 的 `\0`:

```
# 几种错误的代码

(IFS=$'\0' for file in $(find . -print0); do echo $file; done)
# wrong, Command Substitution purges \0

find . -print0 | while read -d '' file; do echo $file; done
# defective, subprocesses spoil side effects

while read -d '' file; do echo $file; done <<< $(echo "$(find . -print0)")
# wrong, Here String and echo pruges \n

$ while IFS= read -r -d '' file; do echo "$file"; done <<!
> $(find . -print0)
> !
# wrong, Command Substitution purges \0
```

这时候才真正体现出 Process Substitution 的优越性:

```
while IFS= read -r -d '' file; do echo $file; done < <(find . -print0)
```

---
# **3. Vim**

Vim 的强大绝不仅仅表现在一个交互式编辑器, 要知道它的前身可是 ex 和 ed, 不要忘了 sed 就是 stream ed, Vim 作为一个非交互的命令行工具也极其强大.

从下面几个方面解读一下:

#### **3.1 匹配闭合括号**

由于 `GNU/grep` 不能处理多行, `awk` 正则又不支持递归正则, 所以 Vim 当仁不让地站了出来.

比如要抠出一个 JSON 里 key 为某个值的 value, 已知 value 是 list:

```
vim -es +'g/PAT/norm n%"ay%' +'redir>>/dev/stdout|echon @a' +qa $filename
```

简单解释一下:

1. `-es` 分别开启 ex mode 和 silent mode, `+` 后面跟 ex command
2. `g/PAT/norm n%"ay%` 是标准的 `global` 命令: `g/pattern/command`
3. `norm n%"ay%` 是使用 normal mode, `n` 让光标移动到匹配的模式上, `%` 跳到下一个闭合的 `]` 上, 然后 `"ay%` 把匹配的 `[` 之间的内容复制到 `a` 寄存器
4. `redir>>/dev/stdout|echon @a` 把 ex command 的输出重定向为标准输出, 然后打印 `a` 寄存器

我们来简单构造数据:

```
{
  "adsfraud_main_test_sg": [
    {
      "addr": "10.65.136.28:31866", 
      "host": "10.65.136.28", 
      "port": 31866, 
      "re_registered_times": [], 
      "registered_time": 1542740589
    }
  ], 
  "amp_render_test_id": [
    {
      "addr": "10.65.136.135:31008", 
      "host": "10.65.136.135", 
      "lb_port": null, 
      "port": 31008, 
      "re_registered_times": [], 
      "registered_time": 1542536853
    }
  ]
}
```

这是我们服务发现的 JSON 格式, 如果不用 Vim 大法, 那么只能 `grep -A20` 粗略列出来, 非常不智能.

运行一下:

```
vim -es  +'g/amp_render_test_id/norm n%"ay%' +'redir>>/dev/stdout|echon @a' +qa s.json
# output:
#                       [
#    {
#      "addr": "10.65.136.135:31008",
#      "host": "10.65.136.135",
#      "lb_port": null,
#      "port": 31008,
#      "re_registered_times": [],
#      "registered_time": 1542536853
#    }
#  ]
```

要注意一个常见的错误:

```
vim -es +'g/PAT/.;/]/p' +qa
```

是不行的, 因为 `/]/` 这个模式只能匹配到下一个 `]`, 数据一旦嵌套就扑街, 比如上面的数据都不行. 我们必须依赖 `%`.

此外, `g/pattern/{range}p` 只能打印出选出的行, 而不是 `[]` 内部的内容. 考虑以下的数据:

```
{ "adsfraud_main_test_sg": [ { "addr": "10.65.136.28:31866", "host": "10.65.136.28", "port": 31866, "re_registered_times": [], "registered_time": 1542740589 } ], "amp_render_test_id": [ { "addr": "10.65.136.135:31008", "host": "10.65.136.135", "lb_port": null, "port": 31008, "re_registered_times": [], "registered_time": 1542536853 } ] }
```

其实和上面的数据内容一样, 只是这次没有格式化, 我们的代码依然可以正确工作, 这是超越了 `global` 命令的!

#### **3.2 处理段落**

段落的定义是以 `\n\n` 分隔的文本, 比如上次有个需求是提取出一个 yaml 文件中所有类型是 cronjob 的并且每天运行的任务的 cmd，yaml 文件长这样：

```
job1:
    cmd: job1
    schedule: "0 18 * * *"
    kind: cronjob

job2:
    kind: cronjob
    cmd: job2
    schedule: "50 18 * * *"

job3:
    kind: daemon
    cmd: ./manage.py corpus_patch_es
```

如果是 awk 的话就要 `awk -F$'\n' RS=` 然后以一大坨数据来处理, awk 的切列本领完全没有用武之地, 就很不划算.

看下 Vim 怎么做:

```
vim -es  +'g/cronjob/exe "norm {:/cmd/p\<Cr>"' +qa j.yaml
```

简单解释下:

1. `exe "norm {:/cmd/p\<Cr>"`: 如果 `norm` 命令中包含 `<Cr>` / `<Esc>` 之类的东西, 那么需要用 `exe "norm"` 的方式执行
2. `{:/cmd/p\<Cr>`, `{` 先回跳到上一个 `\n\n`, 再 `:/cmd/p` 向后搜索并打印, `\<Cr>` 是回车
3. 在 `-es` 模式下 `p` 命令默认打印到 STDOUD, 所以不需要第一个例子里的重定向, 那时我们用了 `echon` 而不是 `p`

你会发现这里的逻辑非常简单, 一切在 Vim 里怎么操作, 你就写下来就可以了, 换成其他任何工具都不可能有这样流畅的体验.

#### **3.3 批修改**

那就更加是 Vim 的拿手好戏了.

首先 diss 垃圾 sed, Vim 命令简单又好:

```
vim +'s/PAT/REPLACE/g' +xa $FILE
```

为什么说更好, 是因为 Vim 所支持的模式简直比肩 PCRE, lookaround, anchor, atomic group, backref, conservative, 除了递归什么都有, 再加上活学活用等号寄存器, 简直无敌.

来看下 NUS 数据库第一次作业里的一道简单题目, 修改一个 csv 文件, 把符合模式的行的第 7 列数字扩大 1.1 倍:

```
vim +'g/PAT/s/\v([^,]+,){6}\zs[^,]+/\=submatch(0)*1.1/' +xa $FILE
```

简单解释下:

1. `s/PAT/REP/` 是 substitute 替换命令
2. `\v([^,]+,){6}\zs[^,]+`, `\v` 开启 very magic 模式, `([^,]+,){6}` 匹配前 6 列, `\zs` 类似环视, 相当于把之前的模式放入 `(?<=PAT)` 里, 最后 `[^,]+` 匹配第 7 列
3. `\=submatch(0)*1.1`, 等号寄存器可以直接用来计算, 所以直接扩大就可以了

也非常直观, 不觉得有任何的困难和别扭的地方, 每个语义都恰到好处.


---
# **4. 其它工具**

#### **4.1 sed**

实际上 sed 已经基本上凉了, 因为讲道理, 大部分正常的机器都会有 Perl5, 那么 sed 的替换功能将完全被 Perl 替换, 并且更加强大. 我们可是在用 PCRE 而不是 sed 那种垃圾 ERE!

比如随手从我的 `~/.history` 里找一个 sed:

额没找到, 很久不用了, 那就从书上抄一个:

```
sed -i 's/\b[0-9]\{3\}\b/NUMBER/g' sed_data.txt
```

这一堆垃圾 escape 真的没人想吐吗? 看看 Perl5:

```
perl -pie 's/\b\d{3}\b/NUMBER/g' sed_data.txt
```

根本不需要死记硬背 ERE 哪些是元字符好吗, 那种愚蠢的东西就应该直接烧掉.

#### **4.2 awk**

awk 唯一的用途就变成了在多列的时候很好用, 模式是这样的:

```
cmd | awk '$1 ~ /PAT1/ && ! /PAT2/ {print $5}' | cmd
```

够了, 不要在 awk 里做奇怪的事情, 什么 getline, 什么 gsub, 行了行了, 再不闭嘴就拉黑.

#### **4.3 grep**

至少, 你要 `brew install grep --with-default-names`.

其次, 你也应该 `brew install pcre`.

然后使用 `pcregrep`, 愉快地使用 atomic group 和递归正则有什么不好. 哦不对,  `pcregrep` 和 `grep -P` 最大区别是 `pcregrep -M` 的多行模式简直就是神器.

我们来看上面 Vim 所解决的两个实例.

**4.3.1 匹配闭合括号**

不想写正则抠 JSON... 因为写出来是这样的:

```
/
(?(DEFINE)
 (?<number>   -? (?= [1-9]|0(?!\d) ) \d+ (\.\d+)? ([eE] [+-]? \d+)? )    
 (?<boolean>   true | false | null )
 (?<string>    " ([^"\\\\]* | \\\\ ["\\\\bfnrt\/] | \\\\ u [0-9a-f]{4} )* " )
 (?<array>     \[  (?:  (?&json)  (?: , (?&json)  )*  )?  \s* \] )
 (?<pair>      \s* (?&string) \s* : (?&json)  )
 (?<object>    \{  (?:  (?&pair)  (?: , (?&pair)  )*  )?  \s* \} )
 (?<json>   \s* (?: (?&number) | (?&boolean) | (?&string) | (?&array) | (?&object) ) \s* )
)
\A (?&json) \Z
/six   
```

我看和吃屎也没啥区别了.

**4.3.2 面向段落**

这个还好:

```
pcregrep -M '(?s)(?<=\n\n|\A).+?cronjob.+?(?=\n\n|\Z)' j.yaml | pcregrep -o1 'cmd:\s*([^\n]+)'
```

emmm, 然而我还是更喜欢 Vim 的做法.

#### **4.4 Here String**

绝对不应该忘记 Here String, 尤其应该意识到它和 Process Substitution 是互补的.

我们将面临以下几种情况:

1. 命令只接受文件, 但是输入来自其他命令的输出.
2. 命令只接受文件, 但是输入来自变量.
3. 命令只接受变量, 但是输入来自其他命令的输出.
4. 命令只接受标准输入, 但是输入来自变量或其他命令的输出.

第一种情况, 我们有 Process Substitution.

第二种情况也很常见, 比如迭代的时候. 我们可以 `echo`:

```
while read var; do cmd <(echo "var"); done
```

由于 `echo` 会忠实打印 `\n` / `\0` / `\t`, 所以应该不会有太大问题, 只是不要忘了 partial quote.

第三种情况, 我们有 Command Substitution.

```
cmd1 $(cmd2)
```

一定要注意 word splitting 的细节, 不引用会用 `IFS` 切词, 反之不会.

第四种情况, 我们有 Here String.

```
cmd <<< $var
cmd1 <<< $(cmd2)
```

一定要注意这里的坑是 Command Substitution 会杀掉 `\0`, 而 `<<<` 又会把 `\n` 换成空格, 除非我们把 Command Substitution 引用起来. 但是引用的后果是破坏切词, 真的很恶劣了!

所以如果真的有特殊字符不能搞定, 第四种情况恐怕还是要用 Process Substitution 绕一圈:

```
(read -r var; cmd $var) < <(echo "$var")
(read -r var; cmd1 $var) < <(cmd2)
```

但是除此之外, Here String 还经常被我用来能够快速修改命令参数.

比如我经常用 `diff <(git cat-file -p <commit1>:<filename>) <(git cat-file -p <commit2>:<filename>)` 这个命令, 但是每次都要移动光标去修改 `commit` 和 `filename` 就很烦, 所以我把它改写成:

```
{ read commit1 commit2 filename; diff <(git cat-file -p $commit1:$filename) <(git cat-file -p $commit2:$filename) ; } <<< "HEAD HEAD^ path/to/file"
```

这样每次通过 [hstr](https://github.com/dvorka/hstr) 翻出来之后直接加上最后三个参数就 okay.

当然如果你写个函数也是可以的, 但是函数的问题是不方便复制, 而我倾向于总是写完整的命令, 便于复制和复用. 同样的理由我不使用 `!!` 之类的东西.

---

# **5. 结论**

结论当然是 Bash 大法吼啊! Bash 真是太爽啦! Better than fucking boys!
