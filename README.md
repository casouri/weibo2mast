# 微博转发毛象bot

支持图片视频，需要服务器（或者自己的电脑）运行。修改自[weibo crawler](https://github.com/dataabc/weibo-crawler)。

## 安装

确保Python3已安装。

```shell
git clone xxx
cd xxx
python -m pip install -r requirements.txt
```

## 配置

1. 修改跟踪的用户
首先根据这个说明拿到user_id：[如何获取user_id](https://github.com/dataabc/weibo-crawler#如何获取user_id)。然后打开`config.json`，修改`"user_id_list"`的内容（参考[程序设置](https://github.com/dataabc/weibo-crawler#3程序设置)）。`config.json`里的其他选项不用管。

2. 新建bot帐号，在设置里选`</> 开发`，`创建新应用`，权限只需要`write`，点`提交`。把`你的访问令牌`对应的一串字符复制下来，保存到`token`文件里。

## 运行

```shell
python xpost.py
```

## Developer

I changed the logging level of `logger_weibo` from `DEBUG` to `WARNING` so the crawler doesn't print posts it crawed.


