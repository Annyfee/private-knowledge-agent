# 配置环境

# py3.12 轻量镜像
FROM python:3.12-slim

# 工作目录
WORKDIR /app

# 注:Docker是按层构建的。只要requirements.txt没改，它就认为这一层已经盖好，不会重新下载安装包。只有更新依赖，才会触发重新安装。这样能极大缩短我们频繁改动代码后的部署时间。
# 所以，我们先拷依赖，再安装对应环境，最后再搬代码。 这样当变更代码时，docker发现依赖没变，就直接复用环境并拷贝一下代码，节省大量性能。 此外，哪怕环境变了，只变一两个环境同样只会安装新加的几个环境而已

# 拷贝依赖文件
COPY requirements.txt .

# pip 稳定安装策略：主源 + 备用源 + 超时重试
RUN python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --extra-index-url https://mirrors.aliyun.com/pypi/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    --trusted-host mirrors.aliyun.com \
    --default-timeout 120 \
    --retries 8

# 搬代码(源路径-目标路径/工作目录):把当前文件夹所有东西全部拷贝到容器里的/app文件夹下
COPY . .

# 启动命令
CMD ["uvicorn","server:app","--host","0.0.0.0","--port","8011"]