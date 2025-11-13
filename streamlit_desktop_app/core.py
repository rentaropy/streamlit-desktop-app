import logging
import multiprocessing
import requests
import socket
import sys
import time
from typing import Optional, Dict

import webview
from streamlit.web import cli as stcli


# <-- 変更点: 特定のポートが空いているかチェックする関数を追加
def is_port_free(port: int) -> bool:
    """Check if a specific port is free.

    Args:
        port: The port number to check.

    Returns:
        True if the port is free, False otherwise.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", port))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return True
    except (socket.error, OSError):
        return False


def find_free_port() -> int:
    """Find an available port on the system.

    This function creates a temporary socket, binds it to an available port,
    and returns that port number. The socket is configured with REUSEADDR
    to ensure the port can be immediately reused.

    Returns:
        int: An available port number that can be used for binding.

    Raises:
        socket.error: If there is an error creating or binding the socket.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def run_streamlit(script_path: str, options: Dict[str, str]) -> None:
    """Run the Streamlit app with specified options in a subprocess.

    This function configures and launches a Streamlit application using the provided
    script and options. It modifies sys.argv to pass the options to Streamlit's CLI.

    Args:
        script_path: Path to the Streamlit script to run. Should be a valid Python
            file that contains a Streamlit application.
        options: Dictionary of Streamlit configuration options. Each key-value pair
            will be converted to a command-line argument in the format --key=value.
            Common options include 'server.port', 'server.address', etc.

    Example:
        >>> options = {
        ...     'server.port': '8501',
        ...     'server.address': 'localhost'
        ... }
        >>> run_streamlit('app.py', options)
    """
    args = ["streamlit", "run", script_path]
    args.extend([f"--{key}={value}" for key, value in options.items()])
    sys.argv = args
    stcli.main()


def wait_for_server(port: int, timeout: int = 10) -> None:
    """Wait for the Streamlit server to start and become responsive.

    This function repeatedly attempts to connect to the Streamlit server
    until it succeeds or times out. It uses HTTP GET requests to check
    if the server is accepting connections.

    Args:
        port: Port number where the server is expected to run. Should be
            a valid port number between 1 and 65535.
        timeout: Maximum time in seconds to wait for the server to start.
            Defaults to 10 seconds.

    Raises:
        TimeoutError: If the server does not become responsive within the
            specified timeout period.
        requests.ConnectionError: If there are network connectivity issues.

    Example:
        >>> try:
        ...     wait_for_server(8501, timeout=15)
        ... except TimeoutError:
        ...     print("Server failed to start")
    """
    start_time = time.time()
    url = f"http://localhost:{port}"
    while True:
        try:
            requests.get(url)
            break
        except requests.ConnectionError:
            if time.time() - start_time > timeout:
                raise TimeoutError("Streamlit server did not start in time.")
            time.sleep(0.1)


def start_desktop_app(
    script_path: str,
    title: str = "Streamlit Desktop App",
    width: int = 1024,
    height: int = 768,
    options: Optional[Dict[str, str]] = None,
    allow_downloads: bool = False,
) -> None:
    """Start the Streamlit app as a desktop application using pywebview.

    This function creates a desktop window that runs a Streamlit application.
    It handles the complete lifecycle of both the Streamlit server and the
    desktop window, including proper cleanup when the window is closed.

    Args:
        script_path: Path to the Streamlit script to run. Should be a valid Python
            file that contains a Streamlit application.
        title: Title of the desktop window. Defaults to "Streamlit Desktop App".
        width: Width of the desktop window in pixels. Defaults to 1024.
        height: Height of the desktop window in pixels. Defaults to 768.
        options: Optional dictionary of additional Streamlit configuration options.
            Note that certain options (server.address, server.headless,
            global.developmentMode) will be overridden by the application.
            'server.port' will be used if specified and available.
        allow_downloads: Whether to allow file downloads in the webview.
            Defaults to False.
            
    Raises:
        FileNotFoundError: If the specified script_path does not exist.
        TimeoutError: If the Streamlit server fails to start within the timeout period.
        RuntimeError: If there are issues with the webview window creation or
            Streamlit process management.

    Example:
        >>> # Basic usage
        >>> start_desktop_app('app.py')
        >>>
        >>> # Custom window size and title
        >>> start_desktop_app(
        ...     'app.py',
        ...     title='My Streamlit App',
        ...     width=1200,
        ...     height=800
        ... )
        >>>
        >>> # With additional Streamlit options
        >>> start_desktop_app(
        ...     'app.py',
        ...     options={
        ...         'theme.primaryColor': '#F63366',
        ...         'theme.backgroundColor': '#FFFFFF'
        ...     }
        ... )
        >>>
        >>> # Allow downloads
        >>> start_desktop_app('app.py', allow_downloads=True)
    """
    if options is None:
        options = {}

    # <-- 変更点: 'server.port' を上書きリストから削除
    overridden_options = [
        "server.address",
        # "server.port", # <-- ユーザー指定を許可するため削除
        "server.headless",
        "global.developmentMode",
    ]
    for opt in overridden_options:
        if opt in options:
            logging.warning(
                f"Option '{opt}' is overridden by the application and will be ignored."
            )

    # <-- 変更点: ポート決定ロジックの開始
    port = 0
    user_specified_port_str = options.get("server.port")

    if user_specified_port_str:
        try:
            user_port = int(user_specified_port_str)
            if is_port_free(user_port):
                port = user_port  # ユーザー指定のポートが空いているので使用する
            else:
                # ユーザーがポートを指定したが、既に使用中だった
                logging.warning(
                    f"Warning: Port {user_port} is already in use. "
                    "A random free port will be assigned."
                )
        except ValueError:
            # ポート番号が 'abc' など、不正な値だった
            logging.warning(
                f"Warning: Invalid port '{user_specified_port_str}'. "
                "A random free port will be assigned."
            )

    # ユーザー指定のポートを使わない場合 (未指定 or 使用中 or 不正値)
    if port == 0:
        port = find_free_port()
    # <-- 変更点: ポート決定ロジックの終了

    # 決定したポートと、他の必須オプションを設定
    options["server.address"] = "localhost"
    options["server.port"] = str(port)
    options["server.headless"] = "true"
    options["global.developmentMode"] = "false"

    # Launch Streamlit in a background process
    multiprocessing.freeze_support()
    streamlit_process = multiprocessing.Process(
        target=run_streamlit, args=(script_path, options)
    )
    streamlit_process.start()

    try:
        # Wait for the Streamlit server to start
        wait_for_server(port)

        if allow_downloads:
            webview.settings['ALLOW_DOWNLOADS'] = True

        # Start pywebview with the Streamlit server URL
        webview.create_window(
            title, f"http://localhost:{port}", width=width, height=height
        )
        webview.start()
    finally:
        # Ensure the Streamlit process is terminated
        streamlit_process.terminate()
        streamlit_process.join()