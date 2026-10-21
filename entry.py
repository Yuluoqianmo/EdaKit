"""PyInstaller 打包入口。

**为什么不能直接把 ``src/edakit/__main__.py`` 当打包入口**：
PyInstaller 是把它当作一个独立的顶层脚本 ``__main__`` 编译的，包的上下文丢失，
于是 ``__main__.py`` 里那句 ``from .cli import main`` 会炸：

    ImportError: attempted relative import with no known parent package

（``python -m edakit`` 能跑，是因为那种调用方式下它有父包。两条路径不一样。）

所以打包用这个文件：它做**绝对导入**，并靠 ``edakit.spec`` 里的
``pathex=["src"]`` 找到包。``python -m edakit`` 仍然走 ``__main__.py``，
两个入口都保留。
"""

from edakit.runtime import configure_background_streams

configure_background_streams()

from edakit.cli import main

if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        import traceback

        traceback.print_exc()
        result = 1
    raise SystemExit(result)
