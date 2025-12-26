# js2python

一个命令行工具，用于将单个 ES5 JavaScript 源文件转换成可运行的 Python 模块，力求保留原始语义并方便后续人工调整。

## 愿景与范围
- 提供轻量 CLI，输入一个 ES5 `.js` 文件，输出一个同等行为的 Python 文件。
- 聚焦 ES5 语法：函数、对象、数组、原型、闭包、`require`/`module.exports` 等核心特性。
- 不处理 TypeScript、ES6+ 新增语法、Promise/async；超出范围的语法将提示用户。

## 领域挑战
- 运行时行为差异：`this` 绑定、原型链、动态属性需要细致映射。
- CommonJS 模块与 Python 模块系统不同，需转换导入/导出模式。
- 内建对象（`Array`、`Object`、`Date` 等）在 Python 中无一一对应，需要适配层。
- 动态类型和隐式类型转换在 Python 中需要额外守护逻辑。

## CLI 体验
### 主要命令
`js2python convert <input.js> [--out <output.py>] [options]`

- 输入限制为单个 ES5 JavaScript 文件；若检测到 ES6+ 语法会警告或拒绝。
- 默认输出路径与输入同目录、同名（扩展名改为 `.py`）。可通过 `--out` 指定。

### 关键选项
- `--runtime {auto,include,skip}`：控制是否在文件末尾追加兼容运行时片段。
- `--strict`：将所有警告提升为错误，适用于 CI。
- `--report <path>`：输出 JSON 格式的转换诊断信息。
- `--debug-ast`：导出 JS AST 与 Python AST 供调试。

### 使用示例
```bash
# 基础转换，输出到同级目录
js2python convert legacy/widget.js

# 指定输出路径并生成诊断报告
js2python convert legacy/data.js --out build/data.py --report reports/data.json
```

## 架构概览
```
CLI -> 解析 -> 语义分析 -> 转换 -> 生成 -> 后处理
          |        |          |        |         |
          v        v          v        v         v
      Config    Scope &    JS→Python  源码     运行时/
      Loader   Prototype     AST      Writer     格式
```

### 核心组件
- **CLI/调度器** (`src/cli.py`): 解析命令、组装配置、串联流水线。
- **配置管理** (`src/config.py`): 处理默认值、`--strict`、输出路径等逻辑。
- **解析器桥接** (`src/parser`): 使用 Esprima/Babel 的 ES5 模式生成 JSON AST，缓存结果。
- **语义分析器** (`src/analyzer`): 构建作用域、判断 `this` 绑定、识别原型链操作、收集告警。
- **转换器** (`src/transformer`): 将 JS AST 节点映射到 Python `ast`，提供针对表达式、语句、模块导出等的规则。
- **生成器** (`src/emitter`): 将 Python AST 写回源码，插入必要注释、运行时代码。
- **运行时适配器** (`src/runtime`): 输出 Array/Date/console 等 ES5 常用 API 的 Python 实现。
- **报告模块** (`src/reporting`): 汇总告警、统计信息，按需写入 JSON。

### 支撑模块
- **缓存层** (`.cache/`): 通过文件哈希缓存解析与转换数据，加速重复操作。
- **规则注册表**: 组织各语法节点的处理函数，便于拓展或替换。
- **诊断系统**: 统一管理警告/错误，包含代码、位置、信息。

## 数据契约
- **解析产物**: `{ ast, hash, meta }` JSON 文件，存储于 `.cache/ast/`。
- **分析数据**: 作用域树、原型关系、可达性标记等结构化对象。
- **转换结果**: `PythonAST` + 告警列表，供生成器使用。
- **诊断记录**: `{file, loc, level, code, message}`，CLI 与报告共用。

## 错误处理策略
- 遇到 ES6+ 或未知语法：在 `--strict` 模式下报错，默认插入 `TODO` 注释并跳过该节点的转换。
- 解析失败或文件 I/O 出错：立即终止并返回非零退出码。
- 转换过程中产生的兼容性风险（如动态属性访问）以警告提示，并在生成代码附近插入注释。

## 推荐目录结构
```
js2python/
├── src/
│   ├── cli.py
│   ├── config.py
│   ├── parser/
│   │   ├── __init__.py
│   │   └── esprima_bridge.py
│   ├── analyzer/
│   │   ├── __init__.py
│   │   └── scope_tracker.py
│   ├── transformer/
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   └── rules/
│   ├── emitter/
│   │   ├── __init__.py
│   │   └── writer.py
│   ├── runtime/
│   │   ├── __init__.py
│   │   └── es5_stdlib.py
│   └── reporting/
│       └── __init__.py
├── runtime_lib/
│   └── ... (Array/Date/console 等 ES5 运行时)
├── tests/
│   ├── fixtures/
│   └── e2e/
├── .cache/ (忽略)
├── js2python.config.json (可选配置示例)
└── README.md
```

## 测试策略
- **单元测试**: 针对转换规则和运行时函数，覆盖典型 ES5 语法（闭包、原型、`arguments` 等）。
- **样例测试**: 使用 Fixtures 对转换结果做文本/AST 快照比对，确保稳定性。
- **行为测试**: 在 Node 中运行 JS 文件，与生成的 Python 文件对比输出，验证语义。
- **运行时测试**: 独立验证兼容层（Array 方法、Date 操作、console API）的行为一致。

## 路线图
1. MVP：支持函数、对象、数组、基本控制流、CommonJS `require/module.exports`、`console`、`JSON` 等核心能力。
2. 原型增强：覆盖原型链动态修改、`Object.create`、继承模式等情况。
3. 动态特性守护：针对 `with`、`eval`、动态属性访问提供更完善的警告与降级策略。
4. 开发体验：CLI 进度展示、诊断分级、更多调试选项。

## 未决问题
- 对 `eval`、`Function` 构造器的处理策略：转换还是直接提示人工介入？
- 是否需要提供可选的 Python 代码风格修饰（如 snake_case 重命名）。
- 当 JS 文件依赖外部模块时，是否自动检测并提示用户逐个转换。

如有特定场景或优先级需求，欢迎反馈以便调整实现顺序。
