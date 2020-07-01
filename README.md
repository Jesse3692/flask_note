# flask学习笔记

> 基于Flask 1.0.2

## 1. 基础用法

### flask最小原型 hello world

```python
from flask import Flask  # 从flask模块导入Flask类

app = Flask(__name__)  # 实例化Flask类


@app.route('/')  # 添加路由
def helloworld():
    return "<h1>helloworld</h1>"


if __name__ == "__main__":
    app.run(debug=True)  # 调用werkzerug中的run_simple
```



### HttpResponse，redirect，render_templater

1.HttpResponse

```python
@app.route("/")
def index():
	return "Hello Flask" # HttpResponse
```

Flask中的 `HttpResponse` 就是直接返回字符串

2.redirect

```python
from flask import redirect

@app.route("/rdt")
def rdt():
	return redirect("/")
```

每当访问`/rdt`这个地址时，视图函数rdt会触发`redirect("/")`跳转到url地址`/`并会触发`/`对应的视图函数`index()`

3.render

```python
from flask import render_template

@app.route("/home")
def home():
	return render_template("home.html")  # 渲染HTML模版并返回HTML页面
```

[以上示例完整代码](https://github.com/Jesse3692/flask_note/blob/master/simple/2.视图函数返回内容.py)

## 2. 进阶用法

## 3. 高级用法

## 4. 源码分析

### [flask最小原型源码解读](https://github.com/Jesse3692/flask_note/blob/master/docs/flask最小原型源码解读.md)
