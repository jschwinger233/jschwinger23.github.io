---
layout: post
---

> Shell programming is a 1950s juke box.  --Larry Wall

Shell 编程 (以下默认为 Bourne Again Shell) 是有趣的，就连 Larry Wall 大神都如是说。接下来的故事大家都知道了，大神嫌 Shell 可读性太高发明了 Perl 与 Perl6，然后赶上 Web1.0 的顺风车站稳 TIOBE 编程语言排行榜前 10，居然到现在都还没死。我是说 Perl。

我是在 2015 年末才开始开始接触到 Shell，吃了多年狗屎，终于总结出一套日常使用 Shell 批处理文件与文本的套路。所以这篇文章的真实标题其实应该是 `Shell in Daily Use` 什么的..

---
### 1. 遍历文件

遍历文件绝对是让人头疼的一件事情，远远比我想象得复杂。

#### 1.1 `find`

首先是 `find` 命令（以下默认为 GNU Findutils，建议 macOS 用户~~去死~~运行 `brew install findutils --with-default-names`），其中最常用的选项大概是 `-name`，比方说递归遍历当前目录下的所有 py 文件然后打印出来：

```shell
find . -name '*.py'
```

然而不要忘了另外几个同样有用的选项 `-path` 与 `-regex`，以及它们的 case-ignore 版本 `-iname` / `-ipath` / `-iregex`，比如搜索在 tests 目录下的 py 文件：

```shell
find . -path '*/tests/*.py'
```

查找所有的名字叫做 folder 的 jpg，不区分大小写：

```shell
find . -iname folder.jpg
```

使用 `-regex` 时建议通过 `-regextype` 选择正则引擎，默认的 `findutils-default` 引擎简直可以去死了。比如查找所有的在 `**/test/` 或者 `**/test/` 之下的 py 文件或者 pyc 文件：

```shell
find . -regex '.*/tests?/.*\.pyc?'  -regextype posix-extended
```

查找所有的名字叫做 folder 的 jpg 或者 png，不区分大小写：
```shell
find . -iregex '.*folder.\(jpg\|png\)' -regextype posix-extended
```

特殊字符的转义是相当恶心的，有时候你真的拿捏不准那些字符在哪些模式下是需要转义才能表达特殊含义，比如如上的 `(` / `)` / `|`。

熟练使用 `-regex` 可以让你少背很多文档，比如由于 `find` 没有 `-exclude`，所以排除目录的话你要么用 `-prune` 要么用 `-regex` 自己撸：

```shell
# 排除 .git 目录之 prune 党
find . -path '*/.git/*' -prune -o -print

# 排除 .git 目录之 regex 党
find . -regex './\([^.]\|\.[^g]\|\.g[^i]\|\.gi[^t]\).*' -regextype posix-extended
```

严格来说，上面的 regex 党的代码并不等价 prune 党，regex 党只是排除了 `./.git/`，而 prune 排除了 `./**/.git/`；但是因为就算是 `-regextype posix-extended` 也不支持惰性 `*` 与 `+`，更别说环视了，所以这就是我们能做到的最好的程度了。

或者是只遍历到二级子目录：

```shell
# 遍历二级子目录之 maxdepth 党
find . -maxdepth 2

# 遍历二级子目录之 regex 党
find . -regex './[^/]*/[^/]*'
```

严格来说，上面 regex 党的代码并不等价 prune 党，regex 严格搜索二级子目录，而 maxdepth 搜索了一级目录与二级，此处 regex 做的事情等价于 `find . -mindepth 2 -maxdepth 2`；并且如果有文件名中包含了 `/` 字符也会导致 regex 出事。

由于 ERE 正则之渣，强烈不建议在过于复杂的需求中使用 `-regex` 吃屎，实在不想写 Python，请老老实实 `find | grep -P` 用 pcre 拯救生命，比如上面的排除 .git 目录就可以写成如下：

```shell
find | grep -P '^(?!.*\.git).*'
```

（你可能需要拜读一番旷世杰作《Mastering Regular Expressions》才能理解上面的正则）

#### 1.2 `for`

`find` 的强大是毋庸置疑的，但是也不要忽略了 `for` 的存在啊，尤其是当我们很清楚我们就是只需要迭代到二级子目录去做一些事情的时候，`for` 能规避很多 `find` 很蛋疼的痛点，稍后会解释，现在先看如何去遍历文件。

首先是正常遍历：

```shell
for filename in *; do echo "$filename"; done
```

这里很有趣的地方就是 `*` 展开时会转义空格等字符，然后 `"filename"` 部分引用（我倾向于称之为 `partial quote` 而不是 `double quote` 是因为这更加 explict）会保证变量不会被 `$IFS` 打断为多个参数传递给函数。

如果有一些过滤条件呢也当然没有问题啦：

```shell
# 默认就是排除 ./.git 的，因为 * 展开不包括隐藏文件

# 包含 .git 进行遍历
for filename in * .git; do echo "$filename"; done

# 只遍历目录，相当于 find -type d
for filename in *; do [ ! -d "$filename" ] && continue; echo "$filename"; done

# 只遍历文件名前缀为 test_ 或者 tests_ 的 py 文件
for filename in *.py; do [[ ! "$filename" =~ test_.*|tests_.* ]] && continue; echo "$filename"; done

# 遍历二级目录
for dirname in *; do for filename in "$dirname"/*; do echo "$filename"; done; done
```

几个需要强调的细节如下：

1. 测试表达式 `[ ... ]` 是很容易出错的，请仅仅在使用 operator 的时候使用它，如上面的 `-d` 检查是否目录，并且保证所有的变量都被部分引用，以及空格都健在，尤其是方括号与其他字符直接的空格。
2. 请使用更加弹性的 `[[ ... ]]` 测试表达式，其中常用的操作不仅包括 `==` 检查相等，更加包括 `=~` 正则表达式匹配。请注意使用 `=~` 时请不要引用右侧的正则表达式。
3. 部分引用会抑制 `*` 展开，所以如果需要拼接二级目录并展开迭代，像上面一样 `for filename in "$dirname"/*` 而不要 `"$dirname/*"`。

多重条件请务必在条件表达式之外使用短路与 `&&` 短路或 `||`，类似 `[ expr1 && expr2 ]` 会死得很难看。虽然你可以使用 `-a` / `-o` operator，但我还是建议统一使用 `&&` / `||`，无论是 `[ ... ]` 还是 `[[ ... ]]`

```shell
# 多重条件之 ||
for dirname in *; do [ ! -d "$dirname" ] || [[ "$dirname" == "tests" ]] && continue; echo "$dirname"; done

# 多重条件之 -o
for dirname in *; do [ ! -d "$dirname" -o "$dirname" == "tests" ] && continue; echo "$dirname"; done
```

如果没有找到匹配模式的文件，a.k.a `*` 展开失败，那么会 for 循环依然会进行一次，但是变量被赋值为未展开的值，所以建议对展开失败的情况进行判断：

```shell
for filename in not_exist_file*; do [ ! -e "$filename" ] && continue; echo "$filename"; done
```

---
### 2. File Name Handling

我们可以遍历文件了，但是如何依次引用每个文件的文件名呢？

#### 2.1 `find`

直接使用 `find` 的 `-exec` 是没问题的，但是会有几个注意事项，先看简单的例子：

```shell
# 删除所有的 py 文件
find . -name '*.py' -exec rm {} \;
```

简单来说呢就是 `{}` 会被替换为 `find` 输出的每个文件名，然后你就可以为所欲为了。最后的 `\;` 只是为了不让 Shell 把 `;` 解释了，这个 `;` 可是要留给 `find` 命令去 interprete 的。

不过删除这种事已经可以被 `find -delete` 做了，所以如果我们要做更复杂的事情怎么办？比如我们要用 Parameter Substitution 把文件名改一下再输出，`{}` 这个破玩意儿肯定是不能 Parameter Substitution 的，但是我们可以利用 `bash -c` 来处理：

```shell
# 把所有的 py 文件后缀改为 python 再输出
find . -name '*.py' -exec /bin/bash -c 'echo "${0/%.py/.python}"' {} \;
```

不熟悉 Shell Parameter Substitution 的朋友建议~~自杀~~通读一遍文档，下同。

可以看到用这种套路我们的 `-exec` 一下子就变得非常灵活了，我们甚至可以写多条语句和循环在 `bash -c` 中，但是需要注意的是 `-exec` 调用了子进程，一切调用子进程的都有两个问题：

1. 环境变量容易坑爹。比如 crond job 动不动就不能执行，多半就是因为环境变量问题，建议 `echo $PATH` 并且调用绝对路径。
2. 子进程中的变量无法（简单）被父进程使用。比如你在子进程中做了什么奇怪的统计然后想累加到父进程的什么变量上，然后运行完了发现父进程的变量还是一字不变，就是踩了子进程的坑。

不过在执行简单任务上这已经完全足够我们折腾了，比如我有个脚本用来转换 flac 到 mp3，就是简单调用 `bash -c` 加上 Parameter Substitution：

```shell
find . -name '*.flac' -exec /bin/bash -c 'ffmpeg -y -i "$0" "${0%.flac}.mp3"' {} \;
```

#### 2.2 `xargs`

xargs 一直被广大人民群众所喜爱，然后年轻人又经常处理不好奇怪的文件名。

正确使用 xargs 的姿势是 `find -print0 | xargs -0` 使用 `\0` 字符分隔文件名，避免文件名中包含 `$IFS` 的文件搞死你：

```shell
find . -name '*.py' -print0 | xargs -0 rm -f
```

对于稍复杂的情况，和上面 `-exec` 一样，祭出 `bash -c` 大法：

```shell
find . -name '*.py' -print0 | xargs -I{} -0 /bin/bash -c 'echo "${0/%.py/.python}"' {}
```

那么这样的话上面那个转换 flac 的脚本就变成了这样：

```shell
find . -name '*.flac' -print0 | xargs -I{} -0 /bin/bash -c 'ffmpeg -y -i "$0" "${0%.flac}.mp3"' {}
```

xargs 最爽的地方就是可以很容易并行，只需要简单加个 `-P` 选项，轻轻松松性能翻番：

```shell
find . -name '*.flac' -print0 | xargs -P0 -I{} -0 /bin/bash -c 'ffmpeg -y -i "$0" "${0%.flac}.mp3"' {}
```

我使用 `-P0` 指定使用尽可能多的进程去运行，使用 `TIME(1)` 去测试性能，转换一张滚石专辑耗时从 `5m46.635s` 跃迁到 `2m36.474s`。

然而 `xargs` 最大的问题是命令存在一个字符数上限，而 `find -exec` 也一样，所以如果特别复杂的命令会有问题，然而一般来说我们不太可能会运行一个 1Kib 的 xargs，而是会写一个 sh 脚本来运行。

我个人的口味来说不喜欢用绝对引用把代码包起来，这会让我的单双引号变得无所适从，所以我愿意用 Here 文档与 Command Substitution 来做这件事：

```shell
find . -name '*.flac' -print0 | xargs -P0 -I{} -0 /bin/bash -c "$(cat <<'EOF'
ffmpeg -y -i "$0" "${0%.flac}.mp3"
EOF
)" {}
```

这样循环啊多重语句啊什么的都可以通过 Here 文档分行，可读性能提高不少，代价是逼格下降不少。

另一个问题是管道总是创建子进程来运行命令，导致的问题是说，如果你希望最终的结果是改变父进程的某个值就会变得非常坑爹了：

```shell
py_cnt=0
find . -name '*.py' -print0 | xargs -0 /bin/bash -c '((py_cnt++))'
echo $py_cnt
```

上面的代码无论如何输出都是 0，就是因为如此。

我们继续前进。

#### 2.3 `read`

read 一开始我是觉得挺难掌握的，主要是内心有点抗拒，觉得 useless，但是上手后迅速就熟练了，发现真的很好用！

比如说处理 `\0` 分隔的输入：

```shell
find . -name '*.py' -print0 | while IFS= read -r -d '' filename; do echo "$filename"; done
```

还是打印 py 文件那一套，主要细节是 `IFS=` 保证了 prefix 的 `$IFS` 不会被 strip，而 `read -d ''` 指明了读取标准输入直到 `\0`，然后在 `while` 循环体内处理 `$filename` 变量就好了。

那么如何才能规避 subshell 的进程隔离问题呢？两个方案：Command Substitution 和 Process Substitution。

使用 Command Substitution 的话需要注意的地方是 `\0` 经过部分引用后就被吃掉了，也就说如下的 shell 脚本是不 work 的：

```shell
# WARNING: not working
while IFS= read -r -d '' filename; do echo "$filename"; done <<<"$(find . -name '*.py' -print0)"
```

所以如果想使用 Command Substitution + Here String 的方法就不能用 `\0` 做分隔。但是如果我们可以肯定都是正常的文件的话，那么用 `\n` 作为分隔也是不错的选择，因此我们不妨这样：

```shell
while IFS= read -r -d $'\n' filename; do echo "$filename"; done <<<"$(find . -name '*.py')"
```

仅仅是简单把 `-d` 的参数从 `''` 改为 `$'\n'`，b.t.w. `''` 也只是 `$'\0'` 的简写；然后让 `find` 命令自然输出，which 分隔符就是 `\n`。

另外一种做法是 Process Substitution：

```shell
while IFS= read -r -d '' filename; do echo "$filename"; done < <(find . -name '*.py' -print0)
```

`<(cmd)` Process Substitution 是非常有用的，它与 `"$(cmd)"` Command Substitution 的区别是很微妙的，前者是把整个命令的输出作为一个输入，后者是把整个命令的输出打印出来，听上去有点 `$*` 之于 `#$@` 的感觉。要注意其中的空格不能多也不能少！

在某些情况下接受标准输入是会出现问题的，因为 while 循环主体与 read 可以读取同一个文件描述符 0，所以一旦 while 循环主体也要读取 stdin 那就坏事了：

```shell
while IFS= read -r -d '' filename; do read -r -d '' line <&0; echo "->$line"; done < <(find . -name '*.py' -print0)
```

如果亲自运行一下再与之前的对比一下就会发现输出的东西少了整整一半，这是隐患，真正出问题的代码不会这么明显地写着从 0 读取。曾经遇到的问题是 `ffmpeg` 居然会调用一个子命令，它们之间居然用 stdin / stdout 来通信，如果你已经用管道占用了 stdin 的话连报错都看不懂。
 
正确的做法应该从另外的文件描述符进行输入，由于使用了 Process Substitution 这是很容易办到的：

```shell
while IFS= read -u3 -r -d '' filename; do echo "$filename"; done 3< <(find . -name '*.py' -print0)
```

唯一的修改就是让 `read -u3` 从 3 读取，然后让 `find` 的输出导入 3。

如此这般，我们现在应该完全可以进行任何的命令了：

```shell
py_cnt=0
while IFS= read -u3 -r -d '' _; do ((py_cnt++)); done 3< <(find . -name '*.py' -print0)
echo $py_cnt
```

再弱弱提一句，read 的 fields split 能力也是超级好用的，比如说要取出 `ls -l` 输出中的 group 与 user，那么可以：

```shell
ls -l | (while read _ _ user group _; do echo "$user -> $group"; done)
```

如果有需要也可是直接修改 `IFS`，轻松切列。

#### 2.4 `for`

我们应该已经有了一个完全可靠的变量文件的脚本了，但是我还是想回过头看一下 for 循环。

使用 for 循环天然就规避了很多问题：

1. 没有使用管道，因此没有 subshell，也不会占用标准输入。
2. `*` 展开自动转义，不需要人工处理 `\0` 之类的东西，省心。

因此如果我们确认一定以及肯定我们遍历的目录深度就是 2，那么请大胆使用 for。我曾经给我的专辑批量加上 mid3v2 标签的时候写过这样的脚本：


```shell
for dir in [1-9]*; do 
    folder="$dir/Folder.jpg"; 
    [ ! -e "$folder" ] && continue; 
    for mp3 in "$dir"/*.mp3; do 
        mid3v2 -p "$folder" "$mp3"; 
    done; 
done
```

同时我想敬告试图使用 for 去迭代 find 输出的朋友，通过修改 IFS 是可以做到的：

```shell
bash <<'EOF'
IFS=$'\n'
for filename in $(find -name '*.py'); do echo "->$filename"; done
EOF
```

但是非常容易出错！第一是建议在 subshell 中运行，避免修改了 IFS 还要切换回来；第二是只能让 IFS 值为 `\n` 而不能为 `\0`，否则在展开 Command Substitution 的时候 `\0` 会被吃掉，然后会变成一坨打印出来；第三是 Command Substitution 一定不能被引用，部分引用也不行 (`"$(find)"`)，否则 Shell 会把整个输出作为一个不可分割的整体塞给 for 去迭代。

---
### 3. 批处理文本

下面来谈谈批处理文本文件的问题，这个需求在实际工作中偶尔会遇到，遇到的时候还挺恶心的。

#### 3.1 `vim`

应该毫不质疑 vim 在这种场景下能够发挥出来的作用。大家对 vim 的认识不应该只停留在一个高效的交互式的文本编辑器上，有时候它也可以不交互。不要忘了它的祖先可是 ex 和 ed。

最常见的问题是批量替换，比方说，我们要批量替换一大大大堆文件里的端口号，40000 -> 40001，比方说，比方说啊。

那么使用 vim 来做的话会很容易：

```shell
vim +'%s/\v<40000>/40001/g' +x <file>
```

给部分 IDE 玩家简单解释一下其中可能陌生的元素：`\v` 表示使用 `very magic` 模式，`<` 与 `>` 在 `very magic` 模式下匹配单词的开始与结束（类似 pcre 里的 `\b`），然后用 `vim +{command}` 来执行 ex 命令。

如果我有多个端口要替换呢，比方说 40000 -> 40001, 30000 -> 30001, 20000 -> 20001：

```shell
cat <<'EOF' >subport.ex
%s/\v<40000>/40001/g
%s/\v<30000>/30001/g
%s/\v<20000>/20001/g
x
EOF
vim -S subport.ex <file>
```

很好理解，就是把 ex 命令都写到一个文件里，然后用 `vim -S` 来执行。

所以要批处理的话就超级简单啦，之前已经做了足够的讨论，因为没有副作用，直接用 `find -exec`：

```shell
find . -type f -exec vim -S subport.ex {} \;
```

但是这样会把每个文件都替换一遍，就算什么都没有也替换一遍，太暴力了，不妨 grep 一下先：

```shell
grep -r . -P '\b[234]0000\b' -lZ | xargs -0 -I{} vim -S subport.ex {}
```

grep 的 `-P` 使用 pcre，`-l` 只输出匹配到的文件名，`-Z` 以 `\0` 作为文件分隔符。奥对了，只有 gnu/grep 才有 `-P`，macOS 用户请 `brew install grep --with-default-names` 吧~

然而仅仅是替换并不能真正体现出 vim ex 的能力啊，必须要提醒一下 `grep` 名称的来源 `g/re/p` 就是 vim 前身 ex 的命令，global 命令才是 ex 的精华。

我们来看这么一个 real world 的需求（感谢 BuBu），现在有一堆文件，要把如下的 `to_delete` logger 删除：

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'loggers': {
        'to_delete': {
            'handlers': ['stdout'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'crumb': {
            'handlers': ['stdout'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
```

用 global 来做的话是很容易的，只要理解了 `g/re/p` 的模式及其变体 `g/re/[range]p` 就很容易解决：

```shell
grep to_delete -r . -lZ | xargs -0 -I{} vim +'g/\v<LOGGING>/ /to_delete/,/}/d' +xa {}
```

重点是管道之后用 vim 运行的 ex 命令，用 `g/re/[range]p` 的模式来拆分的话，`/re/` 是 `/\v<LOGGING>/`，搜索出 LOGGING 单词；`[range]` 是 `/to_delete/,/}/`，从 `to_delete` 到 `}` 直接的行；`p` 是 `d`，即 ex 命令中的删除。
所以整个 ex 命令的意思是：找到每个 `LOGGING` 单词，然后从它之后的代码中把 `to_delete` 至 `}` 直接的行都删除。

或者直接使用 range 命令来操作也是可行的（我就直接撸 ex 好啦，自行脑补上 `grep`）：

```shell
vim +'/to_delete/;/}/d' +xa <file>
```

也很好理解啦，就是搜索出 `to_delete` 到 `}` 之间的行再直接 `d`。请注意细节是 `;` 表明 range 的右边界是从左边界开始搜索的，如果使用 `,` 的话右边界就是与左边界搜索起点相同进行搜索，多半会造成错误的删除。

就是这样。

#### 3.2 `sed`

sed 一度让我沉迷，以致于我居然写出来过 `sed -En ':next; N; $p; '$k',$D; $!b next'` 和 `sed -En '/\{/,/}/{/\{/h; /\{/!H; x; s/(.+)\n(.+)/\2\n\1/; h; /}/p;};'` 这样的代码，真是太可怕了，我现在完全看不懂。

这篇文章的目的将始终致力于让人们在生活中利用 shell 工具提高生产力，沉迷炫技是不对的，虽然我经常这么干。

sed 最常用的用途就是批量替换啦，虽然在已经有 vim 的解决方案下我完全不知道使用 sed 还有什么意义，但是要知道 vim 并不是哪里都有的，比如 Docker 容器内，所以我们还是要掌握一定的 sed 技能。虽然连 vim 都没有的环境多半也没有 sed。

那么还是老问题，把 40000 端口替换为 40001：

```shell
sed -i.bak 's/40000/40001/g' <file>
```

`-i.bak` 表明把被替换的文件做一个备份而不是原地替换，在没有版本控制的环境下这是能救命的。

有意思的地方是 sed 天然能够接受多文件作为输入参数，所以我们（在能够确保没有异形文件名的情况下）可以大胆一点：

```shell
sed -i.bak 's/40000/40001/g' $(grep -P '\b40000\b' -r . -l)
```

这样做的好处是减少了 sed 调用次数与 fork 出来的进程数，同时利用 `grep -P` 我们可以大胆用 pcre 筛选出要替换的文件，而不用拘泥于蹩脚的 ERE，是的，`sed -E` 也是渣。

至于其他的魔幻使用方式，比如 hold 空间什么的，我就这么说吧，正常人根本不会有什么需求会要你用 sed 输出文本文件的倒数 k 行之类的操作（好的我知道 `tail -k`），如果真的发现开始变得恶心起来，请果断用 Python 大法。所以对 sed 的掌握请浅尝辄止。

#### 3.3 `awk`

awk 是一门编程语言，毫无疑问。只不过是古代语言。

然而只有神经病才会天天没事用 `getline` 读取管道再调用 `substr` 之类的函数来做一些奇怪的事情。

让我们着眼于它的优势之处：filter 与 fields split。

比如说众所周知 `docker images --filter` 基本就是废的，那我们想删除名字中包含 `einplus` 的镜像应该怎么做？~~（请 `grep | cut` 党去死，谢谢）~~

```shell
docker rmi -f $(docker images | awk '$1 ~ /einplus/ { print $3 }')
```

用 awk 的话就会非常流畅，`$1` 与 `$3` 非常精确地取出镜像名字与 ID，然后匹配名字、输出 ID。

当然提到切列的时候永远不要忘了 read：

```shell
docker rmi -f $(docker images | while read name _ id _; do [[ "$name" =~ .*einplus.* ]] && echo "$id"; done)
```

也是非常痛快的！

比如我就曾经写过一个命令，批处理我的 mp3 文件，让它们的 TIT2 信息作为文件名，代码是这样的：

```shell
find . -name '*.mp3' -print0 | while read -d '' -r filename; do mid3v2 -l "$filename" | mv "$filename" "${filename%/*}/$(awk -F= '$1 ~ /TIT2/ { print $2 }').mp3"; done
```

可以说是很酣畅淋漓了。

---

说了这么多，其实想熟练使用 Shell 提高生产力，最重要的还是练习啦。相比其他前十语言来说，Shell 的动态弱类型实在是太古灵精怪了，多加一个引号就完全不一样，各种潜规则也层出不穷，多踩chi坑shi，相信明天会更好 \^o^/
