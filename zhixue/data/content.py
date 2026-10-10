"""智学的仿真教学内容（题库 + 课本语料）。

全部为教学用途编写的原创示例内容，用来支撑出题、批改、学情分析、
课本检索四条链路跑通。真实项目里把这部分换成教研的正式题库即可。
"""

from __future__ import annotations

SUBJECTS: list[str] = ["Python", "Java", "前端", "大数据", "软件测试"]

CLASSES: list[tuple[str, str]] = [
    ("智学 Python 就业班 1 班", "2025 级"),
    ("智学 Python 就业班 2 班", "2025 级"),
    ("智学 Java 就业班 1 班", "2025 级"),
]

STUDENT_NAMES: list[str] = [
    "沈砚", "周砚清", "林知远", "徐怀瑾", "顾南川", "叶清和", "苏行止", "白既明",
    "许砚青", "陆时衍", "何清野", "温书言", "程知白", "柳听澜", "谢未晞", "孟星野",
    "裴照野", "江云舒", "宋怀瑾", "于归舟",
]

#: 知识点清单。``textbook`` 是课本语料段落，``questions`` 是题库。
KNOWLEDGE_POINTS: list[dict] = [
    # ------------------------------------------------------------------ Python
    {
        "kp_id": "KP-PY-01",
        "subject": "Python",
        "name": "函数与装饰器",
        "chapter": "Python 进阶 · 函数式编程",
        "difficulty": 3,
        "description": "函数的定义与调用、闭包、装饰器语法糖与常见应用场景。",
        "textbook": [
            "装饰器本质上是一个接收函数并返回函数的高阶函数。"
            "``@decorator`` 只是 ``func = decorator(func)`` 的语法糖，"
            "在模块导入阶段就会完成替换，因此装饰器里的代码在定义时只执行一次，"
            "真正被重复执行的是装饰器内部返回的那个包装函数。",
            "写装饰器时要保留原函数的元信息，标准做法是在包装函数上加 ``@functools.wraps(func)``，"
            "否则 ``__name__``、``__doc__`` 会变成包装函数的，调试和文档生成都会出问题。"
            "如果装饰器需要接收参数，就要再套一层函数，形成“三层结构”："
            "最外层收参数，中间层收被装饰函数，最内层是真正的包装逻辑。",
            "闭包是装饰器的语言基础：内层函数引用了外层函数的变量，"
            "外层函数返回内层函数后，那些变量依然存活在函数对象的 ``__closure__`` 里。"
            "要注意闭包捕获的是变量本身而不是值，在循环里创建多个闭包时容易出现全部捕获到最后一个值的问题。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "关于 Python 装饰器，下列说法正确的是？",
                "options": [
                    "A. 装饰器只能装饰函数，不能装饰类",
                    "B. @decorator 等价于 func = decorator(func)",
                    "C. 装饰器内部代码在被装饰函数每次调用时都会重新执行",
                    "D. 装饰器必须返回被装饰函数本身",
                ],
                "answer": "B",
                "analysis": "装饰器是语法糖，等价于把函数对象传给装饰器并重新赋值；"
                            "装饰器同样可以装饰类；装饰器外层代码只在定义时执行一次。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "为什么写装饰器时推荐使用 functools.wraps？请说明不加会出现什么问题。",
                "answer": "functools.wraps 会把被装饰函数的 __name__、__doc__、__module__、__dict__ "
                          "等元信息复制到包装函数上，并设置 __wrapped__ 属性。"
                          "不加的话，被装饰函数的名称和文档字符串会变成包装函数的，"
                          "导致日志、调试、文档生成以及依赖函数签名的框架出现错误。",
                "analysis": "考察对元信息保留的认识，属于装饰器的工程实践细节。",
            },
            {
                "q_type": "判断",
                "difficulty": 2,
                "stem": "带参数的装饰器，其装饰器参数是在被装饰函数被调用时才传入的。",
                "answer": "错",
                "analysis": "装饰器参数在最外层函数被调用时（即模块导入、执行到装饰语句时）就传入，"
                            "被装饰函数调用时传入的是业务参数。",
            },
        ],
    },
    {
        "kp_id": "KP-PY-02",
        "subject": "Python",
        "name": "列表与字典",
        "chapter": "Python 基础 · 内置容器",
        "difficulty": 2,
        "description": "列表与字典的常用操作、深浅拷贝差异、哈希与可哈希性。",
        "textbook": [
            "列表是可变的有序序列，底层是动态数组，按下标随机访问是 O(1)，"
            "但在头部插入或删除元素是 O(n)，因为需要整体搬移。"
            "如果需要频繁在两端增删，应该使用 ``collections.deque``。",
            "字典是基于哈希表实现的键值映射，平均情况下查找、插入、删除都是 O(1)，"
            "最坏情况退化到 O(n)。字典的键必须是可哈希对象，"
            "列表和字典本身不可哈希，因此不能作为字典的键，但元组（元素全可哈希）可以。",
            "``copy()`` 与 ``[:]`` 都是浅拷贝：只复制最外层容器，"
            "嵌套的对象仍然是同一个引用。要得到完全独立的副本需要 ``copy.deepcopy``，"
            "它会递归复制所有层级，代价也更高。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "下列哪个对象不能作为 Python 字典的键？",
                "options": ["A. 字符串 \"a\"", "B. 元组 (1, 2)", "C. 列表 [1, 2]", "D. 整数 3"],
                "answer": "C",
                "analysis": "字典的键必须可哈希。列表是可变对象，没有稳定的哈希值，因此不能作为键。",
            },
            {
                "q_type": "简答",
                "difficulty": 2,
                "stem": "简述浅拷贝与深拷贝的区别，并说明 copy.deepcopy 的开销为什么更大。",
                "answer": "浅拷贝只复制最外层容器，内部嵌套对象仍与原对象共享引用，"
                          "修改嵌套对象会同时影响两份数据；深拷贝递归复制所有层级的对象，"
                          "得到完全独立的副本。deepcopy 需要递归遍历对象图，"
                          "还要维护 memo 映射来处理循环引用，因此时间和内存开销都更大。",
                "analysis": "考察容器拷贝语义，是排查“改了副本原数据也变”这类 bug 的基础。",
            },
        ],
    },
    {
        "kp_id": "KP-PY-03",
        "subject": "Python",
        "name": "异常处理",
        "chapter": "Python 基础 · 错误处理",
        "difficulty": 2,
        "description": "try/except/else/finally 执行顺序、异常链、自定义异常。",
        "textbook": [
            "``try/except/else/finally`` 的执行顺序是：try 块没有抛异常时执行 else；"
            "无论是否抛异常，finally 都会执行。finally 常用于释放资源，"
            "但要注意如果在 finally 里写 return，会吞掉 try 中正在传播的异常。",
            "捕获异常应遵循“具体到宽泛”的顺序，因为 except 是自上而下匹配的，"
            "把 ``except Exception`` 写在前面会导致后面更具体的分支永远不生效。"
            "裸的 ``except:`` 会连 ``KeyboardInterrupt``、``SystemExit`` 一起吞掉，应当避免。",
            "使用 ``raise ... from exc`` 可以在抛出新的异常时保留原始异常链，"
            "traceback 里会显示“The above exception was the direct cause of...”，"
            "便于定位根因；不加 from 则原始异常会以 During handling of the above exception 的形式出现。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "关于 try/except/else/finally，下列说法错误的是？",
                "options": [
                    "A. else 块在 try 块没有抛出异常时执行",
                    "B. finally 块无论是否发生异常都会执行",
                    "C. finally 中的 return 会覆盖 try 中的 return",
                    "D. 一个 try 只能有一个 except 分支",
                ],
                "answer": "D",
                "analysis": "一个 try 可以有多个 except 分支，按顺序匹配。"
                            "finally 中的 return 确实会覆盖 try 里的返回值，属于常见坑。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "在捕获异常后重新抛出时，raise NewError(...) from exc 相比直接 raise NewError(...) 有什么好处？",
                "answer": "加 from exc 会把原异常设置为新异常的 __cause__，Python 会在 traceback 中"
                          "明确展示“直接原因”，保留完整因果链，便于定位根因；"
                          "不加则原异常只作为 __context__ 隐含携带，显示为“处理上述异常时又发生了异常”，"
                          "容易被误解为两个独立错误。",
                "analysis": "考察异常链的使用，是生产环境排障的关键习惯。",
            },
        ],
    },
    {
        "kp_id": "KP-PY-04",
        "subject": "Python",
        "name": "面向对象",
        "chapter": "Python 进阶 · 对象模型",
        "difficulty": 3,
        "description": "类属性与实例属性、继承与 MRO、魔术方法、property。",
        "textbook": [
            "类属性定义在类体中，被所有实例共享；实例属性在 ``__init__`` 中通过 ``self.x`` 绑定，"
            "只属于当前实例。读取 ``self.x`` 时先查实例字典，找不到才去查类，"
            "而赋值 ``self.x = v`` 永远只写实例字典，这解释了“给某个实例赋值不会影响别人”的现象。",
            "Python 支持多重继承，方法解析顺序由 C3 线性化算法确定，"
            "可以通过 ``ClassName.__mro__`` 查看。MRO 保证了每个类只出现一次，"
            "并且子类总在父类之前，因此 ``super()`` 会沿着 MRO 找下一个类，"
            "而不是简单地找“父类”。",
            "魔术方法让自定义对象融入语言特性：``__str__`` 决定 print 的展示，"
            "``__repr__`` 面向开发者调试，``__eq__`` 定义相等语义，"
            "``__enter__``/``__exit__`` 让对象支持 with 语句。"
            "``@property`` 可以把方法包装成属性访问，从而在不破坏调用方代码的前提下加校验逻辑。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "在多重继承中，super() 的作用是？",
                "options": [
                    "A. 调用父类的父类方法",
                    "B. 返回当前实例的父类对象",
                    "C. 按 MRO 顺序调用下一个类中的同名方法",
                    "D. 调用所有父类的同名方法",
                ],
                "answer": "C",
                "analysis": "super() 沿 C3 线性化得到的 MRO 查找下一个类，"
                            "在菱形继承里能保证每个类的方法只被调用一次。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "解释类属性与实例属性的区别，并说明为什么给实例赋值同名属性不会影响其他实例。",
                "answer": "类属性定义在类体中，属于类对象，所有实例共享；"
                          "实例属性定义在 __init__ 里通过 self 绑定，属于实例自身的 __dict__。"
                          "读取时先找实例字典、再找类；赋值 self.x = v 只会写入当前实例的字典，"
                          "因此不会改动类属性，也不会影响其他实例。",
                "analysis": "考察属性查找顺序，是可变类属性被误共享的根因。",
            },
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "要让一个自定义对象可以用于 with 语句，至少需要实现哪两个方法？",
                "options": [
                    "A. __init__ 和 __del__",
                    "B. __enter__ 和 __exit__",
                    "C. __open__ 和 __close__",
                    "D. __iter__ 和 __next__",
                ],
                "answer": "B",
                "analysis": "with 语句依赖上下文管理器协议，即 __enter__ 与 __exit__。",
            },
        ],
    },
    {
        "kp_id": "KP-PY-05",
        "subject": "Python",
        "name": "文件与上下文管理",
        "chapter": "Python 基础 · IO",
        "difficulty": 2,
        "description": "文件的打开模式、编码、with 语句与流式读取大文件。",
        "textbook": [
            "打开文本文件时应显式指定 ``encoding='utf-8'``。"
            "Windows 中文环境默认编码是 GBK，不指定编码时读取 UTF-8 文件会抛 "
            "``UnicodeDecodeError``，这是跨平台项目最常见的坑之一。",
            "``with open(...) as f`` 会在代码块结束时自动关闭文件，即使中途抛异常也会执行，"
            "它依赖的正是上下文管理器协议。相比手写 try/finally，with 更简洁也更不容易漏写。",
            "读取大文件不要用 ``read()`` 或 ``readlines()`` 一次性载入内存，"
            "应该直接迭代文件对象，或者分块读取：``for line in f`` 每次只保留一行，"
            "内存占用稳定在常量级。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "在 Windows 上读取一个 UTF-8 编码的中文文本文件，最稳妥的写法是？",
                "options": [
                    "A. open(path, 'r')",
                    "B. open(path, 'rb').read().decode('gbk')",
                    "C. open(path, 'r', encoding='utf-8')",
                    "D. open(path, 'r', encoding='ascii')",
                ],
                "answer": "C",
                "analysis": "显式指定 utf-8 可以避免依赖平台默认编码，"
                            "Windows 默认 GBK 会导致乱码或解码异常。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "要统计一个 10GB 日志文件的行数，为什么不能直接用 readlines()，应该怎么写？",
                "answer": "readlines() 会把整个文件读进内存并生成一个巨大的列表，"
                          "遇到 10GB 文件会直接耗尽内存。正确做法是流式迭代："
                          "with open(path, 'r', encoding='utf-8') as f: 然后 for _ in f 计数，"
                          "或者分块读取固定大小的字节并统计换行符，内存占用保持在常量级。",
                "analysis": "考察对内存与流式处理的意识。",
            },
        ],
    },
    # -------------------------------------------------------------------- Java
    {
        "kp_id": "KP-JV-01",
        "subject": "Java",
        "name": "集合框架",
        "chapter": "Java 基础 · 集合",
        "difficulty": 3,
        "description": "ArrayList 与 LinkedList 的差异、HashMap 底层结构、hashCode 与 equals 契约。",
        "textbook": [
            "ArrayList 底层是动态数组，随机访问 O(1)，中间插入删除需要搬移元素为 O(n)；"
            "LinkedList 底层是双向链表，头尾插入删除 O(1)，但随机访问需要遍历为 O(n)。"
            "绝大多数业务场景选 ArrayList，因为 CPU 缓存友好，实际性能往往更好。",
            "HashMap 在 JDK8 之后是“数组 + 链表 + 红黑树”。"
            "当某个桶的链表长度达到 8 且数组容量不小于 64 时，链表会转成红黑树，"
            "把最坏查找从 O(n) 降到 O(log n)；容量不足时优先扩容而不是树化。",
            "重写 equals 必须同时重写 hashCode，这是 Java 的硬性契约："
            "两个 equals 相等的对象必须有相同的 hashCode。"
            "否则把它们作为 HashMap 的键时，会因为哈希值不同落到不同的桶，导致“放进去却取不出来”。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "JDK8 中 HashMap 的链表在什么条件下会转为红黑树？",
                "options": [
                    "A. 链表长度达到 8 时立即转换",
                    "B. 链表长度达到 8 且数组容量不小于 64",
                    "C. 数组容量达到 64 时全部转换",
                    "D. 链表长度达到 16 时转换",
                ],
                "answer": "B",
                "analysis": "树化需要同时满足链表长度 >= 8 和数组容量 >= 64，"
                            "否则优先执行扩容以缩短链表。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "为什么重写 equals 时必须同时重写 hashCode？请结合 HashMap 说明。",
                "answer": "Java 契约要求 equals 相等的两个对象 hashCode 必须相同。"
                          "HashMap 先用 hashCode 定位桶、再用 equals 在桶内比较，"
                          "如果只重写 equals 不重写 hashCode，两个逻辑相等的对象哈希值不同会落到不同桶，"
                          "put 进去的键用逻辑相等的对象 get 不出来，集合也会出现重复元素。",
                "analysis": "经典高频考点，也是真实排障中的常见 bug 来源。",
            },
            {
                "q_type": "判断",
                "difficulty": 2,
                "stem": "LinkedList 的随机访问性能优于 ArrayList。",
                "answer": "错",
                "analysis": "LinkedList 随机访问需要从头或尾遍历链表，"
                            "复杂度 O(n)；ArrayList 基于数组下标直接定位，复杂度 O(1)。",
            },
        ],
    },
    {
        "kp_id": "KP-JV-02",
        "subject": "Java",
        "name": "多线程与并发",
        "chapter": "Java 进阶 · 并发编程",
        "difficulty": 4,
        "description": "线程状态、synchronized 与 Lock、volatile 语义、线程池参数。",
        "textbook": [
            "Java 线程有 NEW、RUNNABLE、BLOCKED、WAITING、TIMED_WAITING、TERMINATED 六种状态。"
            "BLOCKED 特指等待进入 synchronized 临界区，而 WAITING 是调用 wait/join 后的无限等待，"
            "两者在排查线程 dump 时含义完全不同。",
            "volatile 保证可见性和禁止指令重排，但不保证原子性。"
            "像 ``count++`` 这种“读-改-写”三步操作，即使变量是 volatile 的也会丢更新，"
            "必须用 synchronized 或 AtomicInteger 才能保证原子性。",
            "线程池的核心参数是 corePoolSize、maximumPoolSize、workQueue、keepAliveTime 和拒绝策略。"
            "任务提交顺序是：核心线程 -> 队列 -> 非核心线程 -> 拒绝策略。"
            "如果把队列设成无界队列，maximumPoolSize 就永远不会生效，"
            "任务会一直堆积直到内存溢出。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 4,
                "stem": "关于 volatile，下列说法正确的是？",
                "options": [
                    "A. volatile 可以保证复合操作的原子性",
                    "B. volatile 保证可见性并禁止指令重排，但不保证原子性",
                    "C. volatile 会加锁，因此性能与 synchronized 相当",
                    "D. volatile 修饰的变量不能被多个线程共享",
                ],
                "answer": "B",
                "analysis": "volatile 通过内存屏障实现可见性与有序性，不涉及原子性，"
                            "count++ 之类的复合操作仍需同步手段。",
            },
            {
                "q_type": "简答",
                "difficulty": 4,
                "stem": "线程池提交一个新任务时的完整处理顺序是什么？为什么不建议使用无界队列？",
                "answer": "顺序为：核心线程未满则创建核心线程执行；核心线程已满则入队等待；"
                          "队列已满则创建非核心线程；达到 maximumPoolSize 且队列也满时执行拒绝策略。"
                          "使用无界队列时队列永远不会满，maximumPoolSize 形同虚设，"
                          "任务持续堆积会造成内存溢出和响应时间恶化。",
                "analysis": "线程池参数配置是生产事故高发区，属于必须掌握的工程知识。",
            },
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "线程处于 BLOCKED 状态通常是因为？",
                "options": [
                    "A. 调用了 Thread.sleep()",
                    "B. 等待获取 synchronized 锁",
                    "C. 调用了 Object.wait()",
                    "D. 线程已经执行结束",
                ],
                "answer": "B",
                "analysis": "BLOCKED 表示等待监视器锁；sleep 和 wait 对应的分别是 "
                            "TIMED_WAITING 与 WAITING。",
            },
        ],
    },
    {
        "kp_id": "KP-JV-03",
        "subject": "Java",
        "name": "JVM 内存与垃圾回收",
        "chapter": "Java 进阶 · JVM",
        "difficulty": 4,
        "description": "运行时数据区划分、对象分配、GC 算法与分代收集。",
        "textbook": [
            "JVM 运行时数据区包括程序计数器、虚拟机栈、本地方法栈、堆和方法区。"
            "其中程序计数器、虚拟机栈、本地方法栈是线程私有的，堆和方法区（元空间）是线程共享的。"
            "堆是 GC 的主要战场，方法区在 JDK8 之后由元空间实现，使用本地内存。",
            "对象通常优先在新生代的 Eden 区分配。当 Eden 满时触发 Minor GC，"
            "存活对象被复制到 Survivor 区，并在对象头里记录年龄，"
            "年龄达到阈值（默认 15）后晋升到老年代。大对象可能直接进入老年代。",
            "判断对象是否可回收采用可达性分析，从 GC Roots 出发标记可达对象，"
            "不可达的才可能被回收。GC Roots 包括虚拟机栈中引用的对象、"
            "静态属性引用的对象、常量引用的对象和本地方法栈中 JNI 引用的对象。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "下列哪个内存区域是线程共享的？",
                "options": ["A. 程序计数器", "B. 虚拟机栈", "C. 堆", "D. 本地方法栈"],
                "answer": "C",
                "analysis": "堆和方法区为所有线程共享；程序计数器、虚拟机栈、本地方法栈是线程私有的。",
            },
            {
                "q_type": "简答",
                "difficulty": 4,
                "stem": "简述 Minor GC 的触发条件与对象晋升老年代的主要途径。",
                "answer": "当新生代 Eden 区空间不足时触发 Minor GC，"
                          "采用复制算法把 Eden 和当前 Survivor 中的存活对象复制到另一个 Survivor，"
                          "同时对象年龄加一。晋升途径主要有三：年龄达到阈值（默认 15）；"
                          "Survivor 中相同年龄对象总大小超过一半；大对象直接分配到老年代。",
                "analysis": "考察分代收集与对象生命周期，是调优和排查 GC 问题的基础。",
            },
            {
                "q_type": "判断",
                "difficulty": 3,
                "stem": "JVM 通过引用计数法判断对象是否可以被回收。",
                "answer": "错",
                "analysis": "主流 JVM 使用可达性分析而非引用计数法，"
                            "因为引用计数无法处理循环引用。",
            },
        ],
    },
    {
        "kp_id": "KP-JV-04",
        "subject": "Java",
        "name": "异常体系",
        "chapter": "Java 基础 · 异常",
        "difficulty": 2,
        "description": "Error/Exception 层次、受检与非受检异常、try-with-resources。",
        "textbook": [
            "Java 异常体系以 Throwable 为根，分为 Error 和 Exception 两大分支。"
            "Error 表示 JVM 层面的严重问题，如 OutOfMemoryError、StackOverflowError，"
            "应用程序不应尝试捕获处理。",
            "Exception 又分受检异常和非受检异常。受检异常（如 IOException）"
            "编译器强制要求处理或声明抛出；非受检异常继承自 RuntimeException，"
            "如 NullPointerException，编译器不做强制要求。",
            "try-with-resources 要求资源实现 AutoCloseable，"
            "它保证在代码块结束时按“后开先关”的顺序自动调用 close()，"
            "并且当 try 块和 close() 同时抛异常时，close() 的异常会被作为 suppressed 异常挂上去，"
            "不会丢失原始异常。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "下列哪个是所有受检异常和非受检异常的共同父类？",
                "options": ["A. Throwable", "B. Error", "C. Exception", "D. RuntimeException"],
                "answer": "C",
                "analysis": "受检与非受检异常都继承自 Exception，"
                            "而 Error 与 Exception 平级，共同父类是 Throwable。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "try-with-resources 中，如果 try 块和 close() 方法同时抛出异常，会发生什么？",
                "answer": "try 块抛出的异常作为主异常向外传播，"
                          "close() 抛出的异常会通过 addSuppressed 挂到主异常的 suppressed 列表里，"
                          "不会覆盖主异常。这样调用方既能拿到根因，也不会丢失资源释放期的错误信息。",
                "analysis": "考察对 suppressed 异常机制的理解。",
            },
        ],
    },
]


KNOWLEDGE_POINTS.extend([
    # -------------------------------------------------------------------- 前端
    {
        "kp_id": "KP-FE-01",
        "subject": "前端",
        "name": "DOM 操作",
        "chapter": "前端基础 · DOM",
        "difficulty": 2,
        "description": "DOM 树的查询与修改、重排与重绘、DocumentFragment 批量更新。",
        "textbook": [
            "DOM 是浏览器把 HTML 解析成的一棵树，JavaScript 通过 document 提供的 API 读写它。"
            "``querySelector`` / ``querySelectorAll`` 用 CSS 选择器查找节点，"
            "前者返回第一个匹配元素，后者返回静态的 NodeList。",
            "修改 DOM 会触发浏览器重新计算布局（重排，reflow）和重绘（repaint）。"
            "重排代价明显高于重绘，因为它要重新计算元素的位置和大小。"
            "频繁读写样式属性会引发“布局抖动”，因为读操作会强制浏览器立即完成挂起的布局计算。",
            "批量插入节点时应使用 DocumentFragment：先在离屏的片段上组装好所有元素，"
            "再一次性插入文档。这样只触发一次重排，"
            "比循环里逐个 appendChild 少很多次。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "要一次性向页面插入 100 个 li 元素，性能最好的做法是？",
                "options": [
                    "A. 循环里逐个 appendChild 到 ul 上",
                    "B. 先把 li 组装到 DocumentFragment，再一次性插入 ul",
                    "C. 循环里用 innerHTML 累加字符串后赋值",
                    "D. 每次插入后调用 offsetHeight 冲洗布局",
                ],
                "answer": "B",
                "analysis": "DocumentFragment 在内存中组装，最后一次性插入只触发一次重排；"
                            "A 会触发多次，C 会反复解析 HTML 并丢失原有事件绑定，D 会强制同步布局。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "什么是布局抖动（layout thrashing）？如何避免？",
                "answer": "布局抖动指在同一个循环里交替进行样式读取和写入，"
                          "每次读取（如 offsetHeight）都会强制浏览器立即完成尚未合并的布局计算，"
                          "导致反复重排。避免方式是批量读、批量写："
                          "先把需要读的值一次性取完缓存起来，再统一写入样式；"
                          "或者用 requestAnimationFrame 把写操作放到下一帧。",
                "analysis": "前端性能优化的典型问题。",
            },
        ],
    },
    {
        "kp_id": "KP-FE-02",
        "subject": "前端",
        "name": "事件机制",
        "chapter": "前端进阶 · 事件",
        "difficulty": 3,
        "description": "事件流三阶段、事件委托、阻止默认行为与冒泡。",
        "textbook": [
            "DOM 事件流分三个阶段：捕获阶段从 window 向下传到目标元素，"
            "目标阶段在元素本身触发，冒泡阶段从目标向上传回 window。"
            "addEventListener 的第三个参数为 true 时在捕获阶段监听，默认 false 表示冒泡阶段。",
            "事件委托利用冒泡机制，把监听器绑在父元素上，"
            "通过 ``event.target`` 判断实际触发的是哪个子元素。"
            "好处是只需要一个监听器就能管理大量子元素，"
            "并且动态新增的子元素天然生效，不需要重新绑定。",
            "``stopPropagation`` 阻止事件继续传播，"
            "``preventDefault`` 阻止浏览器默认行为（如 a 标签跳转、表单提交），"
            "二者互不替代。要注意 stopPropagation 会破坏事件委托，应谨慎使用。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "关于 addEventListener 的第三个参数，下列说法正确的是？",
                "options": [
                    "A. 传入 true 表示在冒泡阶段监听",
                    "B. 传入 true 表示在捕获阶段监听",
                    "C. 该参数只能传布尔值，不能传对象",
                    "D. 不传时默认在捕获阶段监听",
                ],
                "answer": "B",
                "analysis": "useCapture 为 true 时在捕获阶段触发，默认 false 走冒泡；"
                            "该参数也可以是包含 capture/passive/once 的配置对象。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "简述事件委托的原理及其两个主要优点。",
                "answer": "原理是事件冒泡：子元素触发的事件会逐层向上传播到父元素，"
                          "因此在父元素上绑定一个监听器，通过 event.target 判断实际来源即可处理所有子元素。"
                          "优点一是减少监听器数量、节省内存；"
                          "二是动态新增的子元素自动纳入管理，无需重新绑定。",
                "analysis": "考察对事件流与性能优化的综合理解。",
            },
        ],
    },
    {
        "kp_id": "KP-FE-03",
        "subject": "前端",
        "name": "CSS 盒模型与布局",
        "chapter": "前端基础 · CSS",
        "difficulty": 2,
        "description": "标准盒模型与 IE 盒模型、box-sizing、margin 塌陷、Flex 布局。",
        "textbook": [
            "标准盒模型下 width 只包含内容区，元素实际占宽等于 width + padding + border + margin；"
            "IE 盒模型下 width 已经包含 padding 和 border。"
            "``box-sizing: border-box`` 可以切换到后者，"
            "让尺寸计算更符合直觉，是现代项目的常用默认值。",
            "垂直方向相邻的两个块级元素的 margin 会发生合并，取两者中较大的值，"
            "称为 margin 塌陷。父元素与第一个子元素之间、"
            "父元素在高度为 auto 且没有 padding/border 时与最后一个子元素之间也会塌陷。",
            "Flex 布局通过给父容器设置 ``display: flex`` 开启。"
            "主轴方向由 flex-direction 决定，justify-content 控制主轴对齐，"
            "align-items 控制交叉轴对齐，flex: 1 表示按比例分配剩余空间。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 2,
                "stem": "设置 box-sizing: border-box 后，元素的 width 属性包含哪些部分？",
                "options": [
                    "A. 仅内容区",
                    "B. 内容区 + padding + border",
                    "C. 内容区 + margin",
                    "D. 内容区 + padding + border + margin",
                ],
                "answer": "B",
                "analysis": "border-box 让 width 覆盖内容区、内边距和边框，但不包含外边距。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "什么是 margin 塌陷？给出至少两种会发生的场景。",
                "answer": "margin 塌陷指垂直方向上相邻的外边距合并成一个，取值较大者。"
                          "常见场景：相邻兄弟块级元素的下外边距与上外边距合并；"
                          "父元素与第一个子元素之间，在父元素没有上边框和内边距时合并；"
                          "父元素高度为 auto 且无 padding/border 时与最后一个子元素的下外边距合并。",
                "analysis": "margin 塌陷是布局调试中最常遇到的“诡异间距”来源。",
            },
        ],
    },
    {
        "kp_id": "KP-FE-04",
        "subject": "前端",
        "name": "ES6 核心特性",
        "chapter": "前端进阶 · ES6",
        "difficulty": 3,
        "description": "let/const 与暂时性死区、箭头函数 this、解构、Promise。",
        "textbook": [
            "let 和 const 是块级作用域，存在暂时性死区："
            "从进入作用域到声明语句执行之前，访问该变量会抛 ReferenceError。"
            "const 保证的是绑定不可变，而不是值不可变——"
            "用 const 声明的对象仍然可以修改其属性。",
            "箭头函数没有自己的 this，它的 this 取自定义时所处的外层作用域，"
            "并且不能被 call/apply/bind 改变。"
            "箭头函数也没有 arguments、不能用作构造函数、没有 prototype 属性，"
            "因此不适合作为需要动态 this 的对象方法。",
            "Promise 有三种状态：pending、fulfilled、rejected，状态一旦改变不可逆。"
            "``Promise.all`` 要求全部成功才返回结果，任一失败即整体失败；"
            "``Promise.allSettled`` 则总是等待全部完成并返回每一项的状态，"
            "适合“部分失败也要拿到全部结果”的场景。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "关于箭头函数，下列说法正确的是？",
                "options": [
                    "A. 箭头函数的 this 可以通过 call 修改",
                    "B. 箭头函数的 this 在定义时确定，取自外层作用域",
                    "C. 箭头函数拥有自己的 arguments 对象",
                    "D. 箭头函数可以作为构造函数使用",
                ],
                "answer": "B",
                "analysis": "箭头函数没有自己的 this/arguments/prototype，"
                            "不能 new，this 由词法作用域决定且无法被 call/apply 覆盖。",
            },
            {
                "q_type": "判断",
                "difficulty": 2,
                "stem": "const 声明的对象，其属性值不能被修改。",
                "answer": "错",
                "analysis": "const 约束的是绑定不可重新赋值，对象内部属性仍可修改；"
                            "要冻结对象需使用 Object.freeze。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "Promise.all 与 Promise.allSettled 有什么区别？各自适用于什么场景？",
                "answer": "Promise.all 在全部 Promise 成功时返回结果数组，"
                          "只要有一个 reject 就立即 reject，已成功的结果会被丢弃；"
                          "Promise.allSettled 会等待所有 Promise 结束，"
                          "返回每项 {status, value/reason} 的数组，不会因为失败而中断。"
                          "需要所有数据都成功才继续时用 all；"
                          "需要容错、收集全部结果（如批量上传、并发探测）时用 allSettled。",
                "analysis": "异步并发控制的常见面试与实战考点。",
            },
        ],
    },
    # ------------------------------------------------------------------ 大数据
    {
        "kp_id": "KP-BD-01",
        "subject": "大数据",
        "name": "HDFS 原理",
        "chapter": "大数据基础 · HDFS",
        "difficulty": 3,
        "description": "NameNode/DataNode 架构、副本机制、机架感知、块与元数据。",
        "textbook": [
            "HDFS 采用主从架构：NameNode 负责管理文件系统的命名空间和元数据"
            "（文件与目录树、块到 DataNode 的映射），DataNode 负责实际存储数据块"
            "并定期向 NameNode 发送心跳和块报告。",
            "HDFS 的默认块大小在 Hadoop 2.x 之后是 128MB，默认副本数是 3。"
            "副本放置采用机架感知策略：第一个副本放在客户端所在节点，"
            "第二个放在不同机架的节点，第三个放在与第二个同机架的另一个节点，"
            "兼顾写入带宽与容灾能力。",
            "HDFS 适合一次写入、多次读取的大文件顺序访问场景，"
            "不适合大量小文件：每个文件、每个块都会在 NameNode 内存中占用元数据，"
            "小文件过多会让 NameNode 内存成为瓶颈。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "HDFS 默认的副本放置策略中，第二个副本通常放在？",
                "options": [
                    "A. 与第一个副本相同的节点",
                    "B. 与第一个副本不同机架的节点",
                    "C. 随便一个空闲节点",
                    "D. NameNode 所在节点",
                ],
                "answer": "B",
                "analysis": "机架感知策略要求第二个副本落到不同机架，"
                            "以保证单个机架故障时数据仍然可用。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "为什么 HDFS 不适合存储大量小文件？",
                "answer": "NameNode 在内存中保存整个命名空间的元数据，"
                          "每个文件、每个数据块都对应一条元数据记录。"
                          "小文件数量巨大时，元数据条目数急剧膨胀，"
                          "NameNode 内存迅速耗尽，同时读取小文件需要频繁向 NameNode 请求块位置，"
                          "产生大量 RPC 开销，MapReduce 也会为每个小文件启动一个 map 任务，效率极低。",
                "analysis": "考察对 HDFS 架构瓶颈的理解。",
            },
        ],
    },
    {
        "kp_id": "KP-BD-02",
        "subject": "大数据",
        "name": "MapReduce 流程",
        "chapter": "大数据基础 · MapReduce",
        "difficulty": 4,
        "description": "Map/Shuffle/Reduce 三阶段、Combiner 与 Partitioner、数据倾斜。",
        "textbook": [
            "MapReduce 的执行分为 Map、Shuffle、Reduce 三个阶段。"
            "Map 阶段把输入分片并行处理成键值对；Shuffle 阶段按 key 分区、排序、"
            "把相同 key 的数据汇聚到同一个 Reduce 任务；Reduce 阶段对分组后的数据聚合输出。",
            "Combiner 是 Map 端的本地聚合，作用是在数据进入 Shuffle 之前先做一次合并，"
            "显著减少网络传输。它的前提是聚合操作满足结合律和交换律，"
            "比如求和、求最大值可以，求平均值则不行——"
            "对平均值做 Map 端合并会得到错误结果，除非改成同时携带 sum 和 count。",
            "数据倾斜指少数 key 对应的数据量远超其他 key，"
            "导致个别 Reduce 任务耗时远高于其他任务，拖慢整个作业。"
            "常用缓解手段：给热点 key 加随机前缀做二次聚合、"
            "提高 Reduce 并行度、使用 map-side join 或在倾斜 key 上单独处理。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 4,
                "stem": "下列哪种聚合操作可以直接使用 Combiner？",
                "options": ["A. 求平均值", "B. 求中位数", "C. 求和", "D. 求标准差"],
                "answer": "C",
                "analysis": "Combiner 要求操作满足结合律与交换律。求和、求最值可以；"
                            "平均值、中位数、标准差不行，因为局部结果无法直接合并为全局结果。",
            },
            {
                "q_type": "简答",
                "difficulty": 4,
                "stem": "简述 MapReduce 中 Shuffle 的作用，以及它在整个作业中为什么最关键。",
                "answer": "Shuffle 负责把 Map 的输出按 key 重新分发到对应的 Reduce 任务，"
                          "过程包括分区、排序（溢出写盘时排序）、合并和拉取。"
                          "它之所以关键，是因为需要跨网络传输和磁盘 IO，"
                          "数据量最大、耗时最长，且数据倾斜、内存溢出等故障都集中在这一阶段，"
                          "优化 MR 作业通常就是在优化 Shuffle。",
                "analysis": "Shuffle 是 MapReduce 性能的核心，也是数据倾斜的发生地。",
            },
            {
                "q_type": "判断",
                "difficulty": 3,
                "stem": "MapReduce 中 Reduce 任务的数量可以大于分区（Partition）的数量。",
                "answer": "错",
                "analysis": "Reduce 数量一般等于分区数量，多余的 Reduce 拿不到数据；"
                            "减少 Reduce 数量则会让一个 Reduce 处理多个分区。",
            },
        ],
    },
    {
        "kp_id": "KP-BD-03",
        "subject": "大数据",
        "name": "Spark RDD",
        "chapter": "大数据进阶 · Spark",
        "difficulty": 4,
        "description": "RDD 的不可变与惰性求值、宽依赖窄依赖、缓存与容错。",
        "textbook": [
            "RDD（弹性分布式数据集）是 Spark 的基本抽象，"
            "具有不可变、可分区、可并行计算三大特征。"
            "对 RDD 的转换操作（map、filter 等）是惰性的，"
            "只有遇到行动操作（collect、count、saveAsTextFile）才会真正触发计算。",
            "依赖分为窄依赖和宽依赖。窄依赖指每个父分区最多被一个子分区使用，"
            "如 map、filter，可以在同一个 Stage 内流水线执行；"
            "宽依赖指一个父分区被多个子分区使用，如 groupByKey、join（未做分区优化时），"
            "需要 Shuffle，是划分 Stage 的依据。",
            "RDD 的容错依靠血缘（lineage）：分区丢失时，"
            "可以根据血缘关系重新计算该分区，而不需要像 MapReduce 那样整任务重跑。"
            "对于被反复使用的 RDD，调用 cache/persist 可以避免重复计算，"
            "但缓存会占用内存，且缓存的 RDD 一旦血缘过长仍建议配合 checkpoint 切断血缘。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 4,
                "stem": "下列转换操作中会产生宽依赖、需要 Shuffle 的是？",
                "options": ["A. map", "B. filter", "C. groupByKey", "D. flatMap"],
                "answer": "C",
                "analysis": "map/filter/flatMap 都是一对一的窄依赖；"
                            "groupByKey 需要把相同 key 汇聚，属于宽依赖并触发 Shuffle。",
            },
            {
                "q_type": "简答",
                "difficulty": 4,
                "stem": "spark 的惰性求值是什么意思？它对性能优化有什么意义？",
                "answer": "惰性求值指转换算子不会立即执行，只记录计算逻辑与依赖关系（DAG），"
                          "直到遇到行动算子才真正触发。"
                          "意义在于 Spark 可以在真正执行前对整条 DAG 做优化："
                          "合并窄依赖为同一 Stage 流水线执行，减少中间数据落盘；"
                          "根据全局信息决定分区数和 Shuffle 策略；"
                          "并且不会为最终用不到的中间结果做计算。",
                "analysis": "惰性求值是 DAG 优化与 Stage 划分的前提。",
            },
            {
                "q_type": "判断",
                "difficulty": 3,
                "stem": "对 RDD 调用 cache() 之后，数据会立即被缓存到内存中。",
                "answer": "错",
                "analysis": "cache 只是标记该 RDD 需要缓存，"
                            "真正写入内存发生在第一次行动算子触发计算时。",
            },
        ],
    },
    # ---------------------------------------------------------------- 软件测试
    {
        "kp_id": "KP-TS-01",
        "subject": "软件测试",
        "name": "等价类划分",
        "chapter": "测试设计 · 黑盒方法",
        "difficulty": 2,
        "description": "有效等价类与无效等价类、划分原则、测试用例设计步骤。",
        "textbook": [
            "等价类划分把输入域分成若干子集，认为同一子集中的任意输入"
            "对发现缺陷具有同等效果，因此每个等价类只需取一个代表值测试。"
            "目的是用尽量少的用例覆盖尽量多的输入情况。",
            "等价类分为有效等价类和无效等价类：有效等价类指符合需求规格的合法输入，"
            "检验程序是否实现了应有功能；无效等价类指不合理的输入，"
            "检验程序是否有异常处理能力。设计用例时两类都要覆盖，"
            "且一条用例通常只覆盖一个无效等价类，避免多个错误相互掩盖。",
            "划分等价类后按“最少数量的用例覆盖全部有效等价类、"
            "每条用例只覆盖一个无效等价类”的原则组合用例。"
            "典型划分依据包括输入数据的取值范围、个数、"
            "是否为空、是否满足特定规则（如必须为数字、必须以字母开头）等。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "设计等价类测试用例时，关于无效等价类的处理，正确的原则是？",
                "options": [
                    "A. 一条用例尽可能覆盖多个无效等价类，减少用例数",
                    "B. 一条用例只覆盖一个无效等价类",
                    "C. 无效等价类不需要测试",
                    "D. 无效等价类必须和有效等价类写在同一条用例里",
                ],
                "answer": "B",
                "analysis": "多个无效输入放在一条用例里，"
                            "前面的错误可能导致程序提前退出，后面的错误被掩盖，因此一次只覆盖一个。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "某输入框要求输入 1~100 的整数，请划分等价类并说明可设计的最少用例数。",
                "answer": "有效等价类 1 个：1~100 之间的整数；"
                          "无效等价类至少 3 个：小于 1 的整数、大于 100 的整数、非整数（含字母、小数、空）。"
                          "按每条用例只覆盖一个无效等价类、有效等价类可合并的原则，"
                          "最少需要 4 条用例：1 条覆盖有效类，3 条分别覆盖三个无效类。",
                "analysis": "考察等价类划分的实际应用能力。",
            },
        ],
    },
    {
        "kp_id": "KP-TS-02",
        "subject": "软件测试",
        "name": "边界值分析",
        "chapter": "测试设计 · 黑盒方法",
        "difficulty": 3,
        "description": "边界点与次边界点、与等价类的关系、上点离点内点。",
        "textbook": [
            "边界值分析是等价类划分的补充：大量缺陷出现在输入输出范围的边界上，"
            "因此要重点取边界及其两侧的值。"
            "对于闭区间 [a, b]，标准取值为 a、b（上点），a-1、b+1（离点），"
            "以及区间内任一点（内点）。",
            "边界值通常和等价类划分配合使用：先用等价类确定测试范围，"
            "再用边界值把每条边界取实。对于 [1, 100] 这样的整数区间，"
            "典型用例为 0、1、2、50、99、100、101。",
            "对于开区间和半开区间要特别小心。"
            "区间 (1, 100) 的有效边界点是 2 和 99，而 1 和 100 属于无效输入，"
            "这类“差一错误”正是边界值分析要捕捉的目标。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "对于输入区间 [10, 20] 的整数，下列哪组取值最符合边界值分析？",
                "options": [
                    "A. 5, 15, 25",
                    "B. 9, 10, 11, 19, 20, 21",
                    "C. 10, 20",
                    "D. 1, 10, 100",
                ],
                "answer": "B",
                "analysis": "取上点 10、20，离点 9、21，内点 11、19，"
                            "覆盖边界及其两侧是边界值分析的标准做法。",
            },
            {
                "q_type": "简答",
                "difficulty": 4,
                "stem": "输入要求为大于 1 且小于 100 的整数（开区间），请给出边界值分析的取值并说明理由。",
                "answer": "开区间 (1, 100) 的有效取值边界是 2 和 99，"
                          "因为 1 和 100 本身不合法。"
                          "无效一侧的边界取 1 和 100（恰好越界的最接近值），"
                          "再向外取 0 和 101 验证明显越界。"
                          "因此取值集合为：0、1、2、99、100、101，"
                          "既覆盖有效边界，也覆盖刚越界和明显越界的情况。",
                "analysis": "开区间是边界值分析中最容易出错的情形。",
            },
        ],
    },
    {
        "kp_id": "KP-TS-03",
        "subject": "软件测试",
        "name": "黑盒与白盒测试",
        "chapter": "测试设计 · 方法体系",
        "difficulty": 3,
        "description": "两种方法的关注点、语句与分支覆盖、缺陷发现能力对比。",
        "textbook": [
            "黑盒测试把程序看作一个不透明的盒子，只关注输入与输出的对应关系，"
            "不关心内部实现，常用方法有等价类划分、边界值分析、判定表、"
            "因果图和场景法，主要面向功能验证。",
            "白盒测试关注程序内部结构，依据代码逻辑设计用例，"
            "覆盖标准从弱到强依次为语句覆盖、判定（分支）覆盖、条件覆盖、"
            "判定条件组合覆盖和路径覆盖。覆盖强度越高，用例数量通常越多。",
            "两类方法互补而非替代：黑盒测试用于验证需求是否被正确实现，"
            "能发现功能缺失、流程错误；白盒测试能发现被忽略的分支、"
            "边界条件和冗余逻辑，但无法发现需求本身写错的问题。"
            "实际项目通常先用黑盒保证功能覆盖，再辅以白盒提升代码覆盖率。",
        ],
        "questions": [
            {
                "q_type": "单选",
                "difficulty": 3,
                "stem": "下列属于白盒测试覆盖标准，且覆盖强度高于分支覆盖的是？",
                "options": ["A. 语句覆盖", "B. 判定覆盖", "C. 条件组合覆盖", "D. 功能覆盖"],
                "answer": "C",
                "analysis": "覆盖强度由弱到强为语句、判定、条件、判定条件组合、路径；"
                            "条件组合覆盖强于判定覆盖。",
            },
            {
                "q_type": "简答",
                "difficulty": 3,
                "stem": "为什么说黑盒测试和白盒测试不能互相替代？请举例说明。",
                "answer": "两者关注点不同，能发现的缺陷类型也不同。"
                          "白盒测试即使做到 100% 语句覆盖，也无法发现“需求本身写错”导致的缺陷，"
                          "例如把“登录失败应返回 403”实现成了返回 401，代码全部被执行过但功能仍是错的；"
                          "黑盒测试则无法评估未被任何用例触达的死代码和隐藏分支。"
                          "因此需要黑盒保证需求正确、白盒保证代码路径被充分执行，二者互补。",
                "analysis": "考察对两类方法定位的理解，是测试策略设计的核心认知。",
            },
        ],
    },
])


def knowledge_points_by_subject() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for kp in KNOWLEDGE_POINTS:
        result.setdefault(kp["subject"], []).append(kp)
    return result


__all__ = [
    "SUBJECTS",
    "CLASSES",
    "STUDENT_NAMES",
    "KNOWLEDGE_POINTS",
    "knowledge_points_by_subject",
]
