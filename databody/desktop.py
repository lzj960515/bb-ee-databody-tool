"""用系统 WebView2 显示打包在本地的网页界面。"""
from .desktop_api import DesktopAPI
from .service import application_directory


def main() -> None:
    import webview

    frontend = application_directory() / "frontend" / "index.html"
    api = DesktopAPI()
    window = webview.create_window(
        "苍翼：混沌效应 · 数据体工具",
        url=frontend.resolve().as_uri(),
        js_api=api,
        width=1280,
        height=880,
        min_size=(1050, 720),
        background_color="#f4f5f7",
    )
    api._window = window
    # file:// 直接载入打包资源，不启动本地 HTTP 服务。
    webview.start(gui="edgechromium", http_server=False)


if __name__ == "__main__":
    main()
