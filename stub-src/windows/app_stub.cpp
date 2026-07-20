/**
 * Windows Application Stub (Parent-Child Process + WebView2)
 *
 * Architecture:
 *   app.exe (parent) -> python.exe (child, FastAPI server)
 *   UI mode:      WebView2 window -> http://127.0.0.1:{port}
 *   Console mode: Visible console window, wait for child process
 *   Headless mode: No window, wait for child process
 *
 * Features:
 *   - Single instance (Mutex)
 *   - Job Object for child process lifecycle management
 *   - Health check polling before showing UI
 *   - WebView2 with auto-fallback to console mode
 *   - System tray support (minimize on close)
 *   - Configuration via app.ini + command line arguments
 *   - All project-specific values read from app.ini at runtime
 */

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <winhttp.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <initguid.h>

// WebView2 COM interfaces
#include "WebView2.h"

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "ws2_32.lib")
// Note: #pragma comment(lib) is MSVC-specific; MinGW ignores these.
// Linker flags are specified in the g++ command line instead.

// Define IID_IUnknown for MinGW (needed by COM handler classes)
DEFINE_GUID(IID_IUnknown,
    0x00000000, 0x0000, 0x0000, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46);

// ========== Constants ==========

#define WM_TRAYICON         (WM_USER + 1)
#define WM_SHOWMAINWINDOW   (WM_USER + 2)
#define TRAYICON_ID         1
#define TIMER_SERVER_WAIT   1001
#define TIMER_SERVER_INTERVAL_MS 500
#define SERVER_WAIT_TIMEOUT_SEC 60

// ========== Application Configuration ==========

struct AppConfig {
    char mode[16];          // ui, console, headless
    char title[128];
    int  width;
    int  height;
    int  resizable;
    char start_path[512];
    char close_action[16];  // exit, minimize
    int  show_tray;
    int  pause_on_exit;
    int  port;
    char app_module[128];
    char version_dir[256];
    // Fields for pre-compiled stub (read from app.ini at runtime)
    char app_name[128];     // Application name (for Mutex, window class, messages)
    char stub_version[32];  // Stub version for compatibility check
};

// ========== Global State ==========

static HANDLE g_hChildProcess = NULL;
static HANDLE g_hJob = NULL;
static HANDLE g_hMutex = NULL;
static HWND g_hWnd = NULL;
static HINSTANCE g_hInstance = NULL;
static AppConfig g_cfg = {};
static char g_exeDir[MAX_PATH] = {};
static volatile LONG g_exiting = 0;  // flag: app is shutting down
static int g_serverWaitCount = 0;    // timer tick count for server wait
static bool g_serverReady = false;   // flag: server health check passed
static bool g_navigated = false;     // flag: app URL has been navigated

// Dynamic strings built from app_name
static char g_mutexName[256];      // "{app_name}-SingleInstance"
static char g_wndClassName[256];   // "{app_name}WndClass"

// WebView2 globals
static HMODULE g_hWebView2Dll = NULL;
static ICoreWebView2Controller *g_webviewController = nullptr;
static ICoreWebView2 *g_webview = nullptr;
static ICoreWebView2Controller3 *g_webviewController3 = nullptr;
static bool g_webviewReady = false;

// Tray icon globals
static NOTIFYICONDATAA g_nid = {};
static bool g_trayIconCreated = false;

// ========== Configuration Parsing ==========

static void config_set_defaults(AppConfig *cfg) {
    strncpy(cfg->mode, "ui", sizeof(cfg->mode) - 1);
    cfg->mode[sizeof(cfg->mode) - 1] = '\0';

    // Derive app_name from exe filename (strip path and .exe extension)
    char exePath[MAX_PATH];
    GetModuleFileNameA(NULL, exePath, MAX_PATH);
    const char *exeName = strrchr(exePath, '\\');
    exeName = exeName ? exeName + 1 : exePath;
    strncpy(cfg->app_name, exeName, sizeof(cfg->app_name) - 1);
    cfg->app_name[sizeof(cfg->app_name) - 1] = '\0';
    // Strip .exe extension
    char *dot = strrchr(cfg->app_name, '.');
    if (dot) *dot = '\0';

    // Title defaults to app_name
    strncpy(cfg->title, cfg->app_name, sizeof(cfg->title) - 1);
    cfg->title[sizeof(cfg->title) - 1] = '\0';

    cfg->width = 1280;
    cfg->height = 800;
    cfg->resizable = 1;
    strncpy(cfg->start_path, "/", sizeof(cfg->start_path) - 1);
    cfg->start_path[sizeof(cfg->start_path) - 1] = '\0';
    strncpy(cfg->close_action, "exit", sizeof(cfg->close_action) - 1);
    cfg->close_action[sizeof(cfg->close_action) - 1] = '\0';
    cfg->show_tray = 0;
    cfg->pause_on_exit = 1;
    cfg->port = 8000;

    // app_module defaults to app_name
    strncpy(cfg->app_module, cfg->app_name, sizeof(cfg->app_module) - 1);
    cfg->app_module[sizeof(cfg->app_module) - 1] = '\0';

    // version_dir defaults to app_name (will be overridden by app.ini)
    strncpy(cfg->version_dir, cfg->app_name, sizeof(cfg->version_dir) - 1);
    cfg->version_dir[sizeof(cfg->version_dir) - 1] = '\0';

    strncpy(cfg->stub_version, "1.0.0", sizeof(cfg->stub_version) - 1);
    cfg->stub_version[sizeof(cfg->stub_version) - 1] = '\0';
}

static void config_build_dynamic_strings(AppConfig *cfg) {
    snprintf(g_mutexName, sizeof(g_mutexName), "%s-SingleInstance", cfg->app_name);
    snprintf(g_wndClassName, sizeof(g_wndClassName), "%sWndClass", cfg->app_name);
}

static void config_parse_ini(const char *exeDir, AppConfig *cfg) {
    char iniPath[MAX_PATH];
    snprintf(iniPath, MAX_PATH, "%s\\app.ini", exeDir);

    // Check if ini file exists
    if (GetFileAttributesA(iniPath) == INVALID_FILE_ATTRIBUTES) {
        return;
    }

    char buf[512];

    // Read [app] section
    GetPrivateProfileStringA("app", "name", "", buf, sizeof(buf), iniPath);
    bool appNameFromIni = (buf[0] != '\0');
    if (appNameFromIni) {
        strncpy(cfg->app_name, buf, sizeof(cfg->app_name) - 1);
        cfg->app_name[sizeof(cfg->app_name) - 1] = '\0';
    }

    GetPrivateProfileStringA("app", "module", "", buf, sizeof(buf), iniPath);
    if (buf[0]) {
        strncpy(cfg->app_module, buf, sizeof(cfg->app_module) - 1);
        cfg->app_module[sizeof(cfg->app_module) - 1] = '\0';
    }

    GetPrivateProfileStringA("app", "version_dir", "", buf, sizeof(buf), iniPath);
    if (buf[0]) {
        strncpy(cfg->version_dir, buf, sizeof(cfg->version_dir) - 1);
        cfg->version_dir[sizeof(cfg->version_dir) - 1] = '\0';
    }

    GetPrivateProfileStringA("app", "stub_version", "", buf, sizeof(buf), iniPath);
    if (buf[0]) {
        strncpy(cfg->stub_version, buf, sizeof(cfg->stub_version) - 1);
        cfg->stub_version[sizeof(cfg->stub_version) - 1] = '\0';
    }

    // Read [launch] section
    GetPrivateProfileStringA("launch", "mode", "", buf, sizeof(buf), iniPath);
    if (buf[0]) {
        strncpy(cfg->mode, buf, sizeof(cfg->mode) - 1);
        cfg->mode[sizeof(cfg->mode) - 1] = '\0';
    }

    // Read [ui] section
    bool titleFromIni = false;
    GetPrivateProfileStringA("ui", "title", "", buf, sizeof(buf), iniPath);
    if (buf[0]) {
        strncpy(cfg->title, buf, sizeof(cfg->title) - 1);
        cfg->title[sizeof(cfg->title) - 1] = '\0';
        titleFromIni = true;
    }
    // If app_name was overridden from ini but title was not explicitly set,
    // update title to match the new app_name
    if (appNameFromIni && !titleFromIni) {
        strncpy(cfg->title, cfg->app_name, sizeof(cfg->title) - 1);
        cfg->title[sizeof(cfg->title) - 1] = '\0';
    }

    cfg->width = GetPrivateProfileIntA("ui", "width", cfg->width, iniPath);
    cfg->height = GetPrivateProfileIntA("ui", "height", cfg->height, iniPath);
    cfg->resizable = GetPrivateProfileIntA("ui", "resizable", cfg->resizable, iniPath);

    GetPrivateProfileStringA("ui", "start_path", "", buf, sizeof(buf), iniPath);
    if (buf[0]) {
        strncpy(cfg->start_path, buf, sizeof(cfg->start_path) - 1);
        cfg->start_path[sizeof(cfg->start_path) - 1] = '\0';
    }

    GetPrivateProfileStringA("ui", "close_action", "", buf, sizeof(buf), iniPath);
    if (buf[0]) {
        strncpy(cfg->close_action, buf, sizeof(cfg->close_action) - 1);
        cfg->close_action[sizeof(cfg->close_action) - 1] = '\0';
    }

    cfg->show_tray = GetPrivateProfileIntA("ui", "show_tray", cfg->show_tray, iniPath);

    // Read [console] section
    cfg->pause_on_exit = GetPrivateProfileIntA("console", "pause_on_exit", cfg->pause_on_exit, iniPath);

    // Read [server] section
    cfg->port = GetPrivateProfileIntA("server", "port", cfg->port, iniPath);
}

static void config_parse_args(AppConfig *cfg) {
    int argc = 0;
    LPWSTR *argvW = CommandLineToArgvW(GetCommandLineW(), &argc);

    for (int i = 1; i < argc; i++) {
        if (wcscmp(argvW[i], L"--ui") == 0) {
            strncpy(cfg->mode, "ui", sizeof(cfg->mode) - 1);
            cfg->mode[sizeof(cfg->mode) - 1] = '\0';
        } else if (wcscmp(argvW[i], L"--console") == 0) {
            strncpy(cfg->mode, "console", sizeof(cfg->mode) - 1);
            cfg->mode[sizeof(cfg->mode) - 1] = '\0';
        } else if (wcscmp(argvW[i], L"--headless") == 0) {
            strncpy(cfg->mode, "headless", sizeof(cfg->mode) - 1);
            cfg->mode[sizeof(cfg->mode) - 1] = '\0';
        } else if (wcsncmp(argvW[i], L"--port=", 7) == 0) {
            cfg->port = _wtoi(argvW[i] + 7);
        } else if (wcscmp(argvW[i], L"--help") == 0 || wcscmp(argvW[i], L"-h") == 0) {
            char helpText[1024];
            snprintf(helpText, sizeof(helpText),
                "Usage: %s.exe [options]\n\n"
                "Options:\n"
                "  --ui          UI mode (WebView2 window, default)\n"
                "  --console     Console mode (terminal window)\n"
                "  --headless    Headless mode (no window)\n"
                "  --port=PORT   Specify service port\n"
                "  --help        Show this help",
                cfg->app_name);
            MessageBoxA(NULL, helpText, cfg->app_name, MB_OK | MB_ICONINFORMATION);
            if (argvW) LocalFree(argvW);
            ExitProcess(0);
        }
    }

    if (argvW) LocalFree(argvW);
}

// ========== Health Check (WinHTTP) ==========

// Send POST /api/shutdown to the local server (best-effort, ignores errors)
static void send_shutdown_request(int port) {
    HINTERNET hSession = WinHttpOpen(L"PyApp-Stub/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) return;

    HINTERNET hConnect = WinHttpConnect(hSession, L"127.0.0.1",
        (INTERNET_PORT)port, 0);
    if (!hConnect) {
        WinHttpCloseHandle(hSession);
        return;
    }

    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"POST",
        L"/api/shutdown", NULL, WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return;
    }

    WinHttpSetTimeouts(hRequest, 500, 500, 500, 500);
    WinHttpSendRequest(hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                       WINHTTP_NO_REQUEST_DATA, 0, 0, 0);
    WinHttpReceiveResponse(hRequest, NULL);

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
}

static bool check_health(int port, DWORD timeoutMs = 1000) {
    HINTERNET hSession = WinHttpOpen(
        L"PyApp-Stub/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) return false;

    WinHttpSetTimeouts(hSession, timeoutMs, timeoutMs, timeoutMs, timeoutMs);

    HINTERNET hConnect = WinHttpConnect(hSession, L"127.0.0.1", (INTERNET_PORT)port, 0);
    if (!hConnect) {
        WinHttpCloseHandle(hSession);
        return false;
    }

    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect, L"GET", L"/api/health",
        NULL, WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return false;
    }

    bool result = false;
    if (WinHttpSendRequest(hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                           WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
        WinHttpReceiveResponse(hRequest, NULL)) {
        DWORD statusCode = 0, sz = sizeof(statusCode);
        if (WinHttpQueryHeaders(hRequest,
                WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                WINHTTP_HEADER_NAME_BY_INDEX, &statusCode, &sz,
                WINHTTP_NO_HEADER_INDEX)) {
            result = (statusCode == 200);
        }
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
    return result;
}

// Check if a TCP port is available for binding.
// Uses bind() WITHOUT SO_REUSEADDR. On Windows, SO_REUSEADDR allows
// "port stealing" (binding to a port another process is already listening on),
// which makes the check unreliable. Without SO_REUSEADDR, bind() succeeds
// only for truly free ports and fails for ports in TIME_WAIT or in use.
// A port in TIME_WAIT will fail this check, but that's acceptable because:
//   1. We've already verified with check_health() that no server is listening.
//   2. uvicorn with reuse_address=True can still bind to TIME_WAIT ports.
//   3. The warning message is non-fatal (application proceeds anyway).
static bool is_port_available(int port) {
    // Initialize WinSock once; skip WSACleanup to avoid affecting other
    // components. The OS cleans up when the process exits.
    static bool s_wsaInitialized = false;
    if (!s_wsaInitialized) {
        WSADATA wsaData;
        if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) return true;
        s_wsaInitialized = true;
    }

    SOCKET sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock == INVALID_SOCKET) {
        return true;  // Assume available
    }

    struct sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons((u_short)port);

    bool available = (bind(sock, (struct sockaddr*)&addr, sizeof(addr)) == 0);

    closesocket(sock);
    return available;
}

// Check if the child process is still running
static bool is_child_running() {
    if (!g_hChildProcess) return false;
    DWORD exitCode = 0;
    if (!GetExitCodeProcess(g_hChildProcess, &exitCode)) return false;
    return (exitCode == STILL_ACTIVE);
}

// ========== Child Process Management ==========

static bool start_child_process() {
    char cmdLine[MAX_PATH * 3];
    snprintf(cmdLine, sizeof(cmdLine),
        "\"%s\\runtime\\%s-runtime.exe\" -m %s",
        g_exeDir, g_cfg.app_name, g_cfg.app_module);

    // Set environment variables
    SetEnvironmentVariableA("APP_MODE", "production");

    char pythonpath[MAX_PATH * 4];
    snprintf(pythonpath, sizeof(pythonpath),
        "%s\\%s\\app;%s\\%s\\app_packages",
        g_exeDir, g_cfg.version_dir, g_exeDir, g_cfg.version_dir);
    SetEnvironmentVariableA("PYTHONPATH", pythonpath);

    // Set port environment variable
    char portStr[16];
    snprintf(portStr, sizeof(portStr), "%d", g_cfg.port);
    SetEnvironmentVariableA("APP_PORT", portStr);

    // Create Job Object
    g_hJob = CreateJobObjectA(NULL, NULL);
    if (!g_hJob) return false;

    JOBOBJECT_EXTENDED_LIMIT_INFORMATION jeli = {};
    jeli.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(g_hJob, JobObjectExtendedLimitInformation,
                                  &jeli, sizeof(jeli))) {
        CloseHandle(g_hJob);
        g_hJob = NULL;
        return false;
    }

    // Determine creation flags based on mode
    DWORD creationFlags;
    if (strcmp(g_cfg.mode, "console") == 0) {
        creationFlags = CREATE_NEW_CONSOLE | CREATE_SUSPENDED;
    } else {
        // UI and headless mode: hide the console
        creationFlags = CREATE_NO_WINDOW | CREATE_SUSPENDED;
    }

    STARTUPINFOA si = { sizeof(si) };
    PROCESS_INFORMATION pi = {};

    // Work directory must be runtime dir for _pth relative paths to work correctly
    // Embeddable Python ignores PYTHONPATH, only uses _pth file
    char workDir[MAX_PATH];
    snprintf(workDir, sizeof(workDir), "%s\\runtime", g_exeDir);

    BOOL success = CreateProcessA(
        NULL, cmdLine, NULL, NULL, FALSE,
        creationFlags, NULL, workDir, &si, &pi);

    if (!success) {
        char errorMsg[512];
        snprintf(errorMsg, sizeof(errorMsg),
            "Failed to start application.\n\nCommand: %s\nWorkDir: %s\nError Code: %lu",
            cmdLine, workDir, GetLastError());
        char msgTitle[256];
        snprintf(msgTitle, sizeof(msgTitle), "%s - Error", g_cfg.app_name);
        MessageBoxA(NULL, errorMsg, msgTitle, MB_ICONERROR);
        CloseHandle(g_hJob);
        g_hJob = NULL;
        return false;
    }

    // Assign to job object (critical for preventing orphan processes)
    if (!AssignProcessToJobObject(g_hJob, pi.hProcess)) {
        // Job assignment failed - KILL_ON_JOB_CLOSE won't work for grandchild processes.
        // Common cause: child process is already in another non-breakaway job.
        // Non-fatal: TerminateProcess will still kill the direct child, but
        // grandchild processes (e.g., subprocess.Popen) may survive as orphans.
        char dbgMsg[512];
        snprintf(dbgMsg, sizeof(dbgMsg),
            "%s: WARNING - AssignProcessToJobObject failed, "
            "grandchild processes may not be cleaned up\n", g_cfg.app_name);
        OutputDebugStringA(dbgMsg);
    }

    // Resume the process
    ResumeThread(pi.hThread);

    g_hChildProcess = pi.hProcess;
    CloseHandle(pi.hThread);

    return true;
}

static void terminate_child() {
    if (InterlockedExchange(&g_exiting, 1) != 0) {
        return;  // Already terminating, prevent re-entry
    }

    if (g_hChildProcess) {
        // Step 1: Try graceful shutdown via POST /api/shutdown.
        // This gives the Python server a chance to finish in-flight requests,
        // flush buffers, and close resources cleanly. The server calls
        // os._exit(0) ~0.5s after receiving this request.
        send_shutdown_request(g_cfg.port);

        // Step 2: Wait up to 1 second for the process to exit gracefully.
        DWORD waitResult = WaitForSingleObject(g_hChildProcess, 1000);

        // Step 3: If the process didn't exit gracefully, force-terminate it.
        // This handles cases where the server is hung or unresponsive.
        if (waitResult == WAIT_TIMEOUT) {
            TerminateProcess(g_hChildProcess, 0);
            WaitForSingleObject(g_hChildProcess, 3000);
        }

        CloseHandle(g_hChildProcess);
        g_hChildProcess = NULL;
    }

    // Close Job Object - triggers KILL_ON_JOB_CLOSE for grandchild processes.
    if (g_hJob) {
        CloseHandle(g_hJob);
        g_hJob = NULL;
    }
}

// ========== Console Ctrl Handler (prevent orphan processes) ==========

static BOOL WINAPI console_ctrl_handler(DWORD ctrlType) {
    // Handle Ctrl+C, Ctrl+Break, close, logoff, shutdown
    switch (ctrlType) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
    case CTRL_CLOSE_EVENT:
    case CTRL_LOGOFF_EVENT:
    case CTRL_SHUTDOWN_EVENT:
        if (g_hWnd) {
            // UI mode: post WM_CLOSE to let the main thread handle shutdown.
            // This avoids data races between this thread and the main thread
            // on g_hChildProcess / g_hJob / g_webview etc.
            PostMessage(g_hWnd, WM_CLOSE, 0, 0);
        } else {
            // Console/headless mode: no message loop, terminate directly.
            // Race condition with main thread is unlikely in practice because
            // the main thread is blocked in WaitForSingleObject(g_hChildProcess),
            // which returns immediately after TerminateProcess.
            terminate_child();
        }
        return TRUE;
    }
    return FALSE;
}

static void install_ctrl_handler() {
    SetConsoleCtrlHandler(console_ctrl_handler, TRUE);
}

// ========== System Tray ==========

static void create_tray_icon(HWND hwnd) {
    if (g_trayIconCreated) return;

    memset(&g_nid, 0, sizeof(g_nid));
    g_nid.cbSize = sizeof(g_nid);
    g_nid.hWnd = hwnd;
    g_nid.uID = TRAYICON_ID;
    g_nid.uFlags = NIF_ICON | NIF_TIP | NIF_MESSAGE;
    g_nid.uCallbackMessage = WM_TRAYICON;
    g_nid.hIcon = NULL;
    {
        char exePath[MAX_PATH];
        GetModuleFileNameA(NULL, exePath, MAX_PATH);
        HICON hLarge = NULL, hSmall = NULL;
        if (ExtractIconExA(exePath, 0, &hLarge, &hSmall, 1) > 0) {
            g_nid.hIcon = hSmall ? hSmall : hLarge;
        }
    }
    if (!g_nid.hIcon) {
        g_nid.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    }
    strncpy(g_nid.szTip, g_cfg.app_name, sizeof(g_nid.szTip) - 1);
    g_nid.szTip[sizeof(g_nid.szTip) - 1] = '\0';

    Shell_NotifyIconA(NIM_ADD, &g_nid);
    g_trayIconCreated = true;
}

static void remove_tray_icon() {
    if (g_trayIconCreated) {
        Shell_NotifyIconA(NIM_DELETE, &g_nid);
        g_trayIconCreated = false;
    }
}

static void show_tray_menu(HWND hwnd) {
    POINT pt;
    GetCursorPos(&pt);

    HMENU hMenu = CreatePopupMenu();
    AppendMenuA(hMenu, MF_STRING, 1, "Show Window");
    AppendMenuA(hMenu, MF_SEPARATOR, 0, NULL);
    AppendMenuA(hMenu, MF_STRING, 2, "Exit");

    // Need to set foreground window for the menu to dismiss properly
    SetForegroundWindow(hwnd);

    int cmd = TrackPopupMenu(hMenu, TPM_RETURNCMD | TPM_NONOTIFY,
                             pt.x, pt.y, 0, hwnd, NULL);

    DestroyMenu(hMenu);

    if (cmd == 1) {
        // Show window
        ShowWindow(hwnd, SW_SHOW);
        SetForegroundWindow(hwnd);
    } else if (cmd == 2) {
        // Exit
        DestroyWindow(hwnd);
    }
}

// ========== WebView2 Integration ==========

// Get the DPI scale factor for the monitor that the window is on
static double get_dpi_scale(HWND hwnd) {
    HMONITOR hMonitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
    if (!hMonitor) return 1.0;

    // Try GetDpiForMonitor (Windows 8.1+, exported from shcore.dll)
    HMODULE hShcore = LoadLibraryExA("shcore.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (hShcore) {
        typedef HRESULT (WINAPI *PFN_GetDpiForMonitor)(HMONITOR, int, UINT*, UINT*);
        auto pfn = (PFN_GetDpiForMonitor)GetProcAddress(hShcore, "GetDpiForMonitor");
        if (pfn) {
            UINT dpiX = 96, dpiY = 96;
            // MDT_EFFECTIVE_DPI = 0
            if (SUCCEEDED(pfn(hMonitor, 0, &dpiX, &dpiY))) {
                FreeLibrary(hShcore);
                return (double)dpiX / 96.0;
            }
        }
        FreeLibrary(hShcore);
    }

    // Fallback: GetDpiForWindow (Windows 10 1607+, in user32.dll)
    HMODULE hUser32 = GetModuleHandleA("user32.dll");
    if (hUser32) {
        typedef UINT (WINAPI *PFN_GetDpiForWindow)(HWND);
        auto pfn = (PFN_GetDpiForWindow)GetProcAddress(hUser32, "GetDpiForWindow");
        if (pfn) {
            UINT dpi = pfn(hwnd);
            return (double)dpi / 96.0;
        }
    }

    return 1.0;
}

// Update WebView2 rasterization scale for current DPI
static void update_webview_dpi() {
    if (!g_webviewController3 || !g_hWnd) return;

    double scale = get_dpi_scale(g_hWnd);
    g_webviewController3->put_RasterizationScale(scale);

    // Resize with raw (physical pixel) bounds
    RECT bounds;
    GetClientRect(g_hWnd, &bounds);
    g_webviewController->put_Bounds(bounds);
}

static void resize_webview() {
    if (g_webviewController && g_hWnd) {
        if (g_webviewController3) {
            // DPI-aware: update scale and use raw bounds
            update_webview_dpi();
        } else {
            // Fallback: no DPI awareness
            RECT bounds;
            GetClientRect(g_hWnd, &bounds);
            g_webviewController->put_Bounds(bounds);
        }
    }
}

// Build the application URL for WebView2 navigation
static void build_app_url(WCHAR *buf, size_t bufSize) {
    swprintf(buf, bufSize, L"http://127.0.0.1:%d%hs", g_cfg.port, g_cfg.start_path);
}

// Callback: WebView2 controller created
class ControllerHandler : public ICoreWebView2CreateCoreWebView2ControllerCompletedHandler {
    ULONG m_ref = 1;
public:
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Controller *controller) override {
        if (FAILED(result) || !controller) {
            // WebView2 failed, fall back to console mode
            MessageBoxA(NULL,
                "WebView2 initialization failed.\nSwitching to console mode.",
                g_cfg.app_name, MB_ICONWARNING);
            strncpy(g_cfg.mode, "console", sizeof(g_cfg.mode) - 1);
            g_cfg.mode[sizeof(g_cfg.mode) - 1] = '\0';
            PostMessage(g_hWnd, WM_CLOSE, 0, 0);
            return S_OK;
        }

        g_webviewController = controller;
        controller->AddRef();

        // Get the CoreWebView2
        controller->get_CoreWebView2(&g_webview);
        if (!g_webview) {
            strncpy(g_cfg.mode, "console", sizeof(g_cfg.mode) - 1);
            g_cfg.mode[sizeof(g_cfg.mode) - 1] = '\0';
            PostMessage(g_hWnd, WM_CLOSE, 0, 0);
            return S_OK;
        }

        // Configure settings
        ICoreWebView2Settings *settings = nullptr;
        g_webview->get_Settings(&settings);
        if (settings) {
            settings->put_IsScriptEnabled(TRUE);
            settings->put_AreDefaultScriptDialogsEnabled(TRUE);
            settings->put_IsStatusBarEnabled(FALSE);
            settings->put_AreDevToolsEnabled(FALSE);
            settings->put_IsZoomControlEnabled(FALSE);  // Disable Ctrl+wheel/pinch zoom
            settings->Release();
        }

        // Try to get ICoreWebView2Controller3 for DPI-aware rendering
        if (SUCCEEDED(controller->QueryInterface(IID_ICoreWebView2Controller3,
                                                  (void**)&g_webviewController3))) {
            // One-time DPI configuration
            g_webviewController3->put_BoundsMode(COREWEBVIEW2_BOUNDS_MODE_USE_RAW_BOUNDS);
            g_webviewController3->put_ShouldDetectMonitorScaleChanges(TRUE);
        } else {
            g_webviewController3 = nullptr;
        }

        // Resize WebView to fill the window (with DPI handling)
        resize_webview();

        // Show loading page immediately (server may not be ready yet)
        // The timer in run_ui_mode will navigate to the real URL once ready
        const char *loadingHtml = R"(
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    display: flex; align-items: center; justify-content: center;
    height: 100vh; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f5f5f5; color: #666;
}
.container { text-align: center; }
.spinner {
    width: 36px; height: 36px; margin: 0 auto 20px;
    border: 3px solid #e0e0e0; border-top-color: #1890ff;
    border-radius: 50%; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="container">
    <div class="spinner"></div>
    <p>Starting...</p>
</div>
</body>
</html>)";
        WCHAR wHtml[2048];
        if (MultiByteToWideChar(CP_UTF8, 0, loadingHtml, -1, wHtml, 2048) == 0) {
            wHtml[0] = L'\0';
        }
        g_webview->NavigateToString(wHtml);

        g_webviewReady = true;

        // If the server is already ready, navigate immediately instead of
        // waiting for the next timer tick. This avoids the race condition
        // where the health check succeeds before WebView2 is initialized.
        if (g_serverReady && !g_navigated) {
            g_navigated = true;
            WCHAR url[512];
            build_app_url(url, 512);
            g_webview->Navigate(url);
            KillTimer(g_hWnd, TIMER_SERVER_WAIT);
        }

        return S_OK;
    }

    // IUnknown - proper reference counting
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
        if (riid == IID_IUnknown || riid == IID_ICoreWebView2CreateCoreWebView2ControllerCompletedHandler) {
            *ppv = this;
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&m_ref); }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG ref = InterlockedDecrement(&m_ref);
        if (ref == 0) delete this;
        return ref;
    }
};

// Callback: WebView2 environment created
class EnvironmentHandler : public ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler {
    ULONG m_ref = 1;
public:
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Environment *env) override {
        if (FAILED(result) || !env) {
            MessageBoxA(NULL,
                "Failed to create WebView2 environment.\nSwitching to console mode.",
                g_cfg.app_name, MB_ICONWARNING);
            strncpy(g_cfg.mode, "console", sizeof(g_cfg.mode) - 1);
            g_cfg.mode[sizeof(g_cfg.mode) - 1] = '\0';
            PostMessage(g_hWnd, WM_CLOSE, 0, 0);
            return S_OK;
        }

        // Create the controller (async - handler self-manages via refcount)
        auto handler = new ControllerHandler();
        env->CreateCoreWebView2Controller(g_hWnd, handler);
        handler->Release();  // Release our ownership; WebView2 holds its own ref
        return S_OK;
    }

    // IUnknown - proper reference counting
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
        if (riid == IID_IUnknown || riid == IID_ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler) {
            *ppv = this;
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&m_ref); }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG ref = InterlockedDecrement(&m_ref);
        if (ref == 0) delete this;
        return ref;
    }
};

static bool create_webview() {
    // Load WebView2Loader.dll at runtime
    // Search order: exe directory -> system directories
    WCHAR loaderPath[MAX_PATH];
    MultiByteToWideChar(CP_ACP, 0, g_exeDir, -1, loaderPath, MAX_PATH);
    snwprintf(loaderPath + wcslen(loaderPath), MAX_PATH - wcslen(loaderPath),
              L"\\WebView2Loader.dll");

    HMODULE hWebView2 = LoadLibraryW(loaderPath);
    if (!hWebView2) {
        // Try without path (system directories)
        hWebView2 = LoadLibraryW(L"WebView2Loader.dll");
    }
    if (!hWebView2) {
        // WebView2 not available, fall back to console mode
        MessageBoxA(NULL,
            "WebView2 Runtime is not installed.\n\n"
            "Please install Microsoft Edge WebView2 Runtime:\n"
            "https://developer.microsoft.com/en-us/microsoft-edge/webview2/\n\n"
            "Switching to console mode.",
            g_cfg.app_name, MB_ICONWARNING);
        strncpy(g_cfg.mode, "console", sizeof(g_cfg.mode) - 1);
        g_cfg.mode[sizeof(g_cfg.mode) - 1] = '\0';
        return false;
    }

    // Get the factory function
    auto pfnCreateEnv = (PFNCreateCoreWebView2EnvironmentWithOptions)
        GetProcAddress(hWebView2, "CreateCoreWebView2EnvironmentWithOptions");
    if (!pfnCreateEnv) {
        MessageBoxA(NULL,
            "WebView2Loader.dll is invalid.\nSwitching to console mode.",
            g_cfg.app_name, MB_ICONWARNING);
        FreeLibrary(hWebView2);
        strncpy(g_cfg.mode, "console", sizeof(g_cfg.mode) - 1);
        g_cfg.mode[sizeof(g_cfg.mode) - 1] = '\0';
        return false;
    }

    // Save DLL handle for cleanup on exit
    g_hWebView2Dll = hWebView2;

    // Use userDataFolder in app directory to avoid permission issues
    WCHAR userDataDir[MAX_PATH];
    MultiByteToWideChar(CP_ACP, 0, g_exeDir, -1, userDataDir, MAX_PATH);
    snwprintf(userDataDir + wcslen(userDataDir), MAX_PATH - wcslen(userDataDir),
              L"\\webview_data");

    auto handler = new EnvironmentHandler();
    HRESULT hr = pfnCreateEnv(
        nullptr,       // browserDirPath: use installed WebView2 Runtime
        userDataDir,   // userDataFolder
        nullptr,       // environmentOptions
        handler);
    handler->Release();  // Release our ownership; WebView2 holds its own ref

    return SUCCEEDED(hr);
}

static void destroy_webview() {
    if (g_webview) {
        g_webview->Release();
        g_webview = nullptr;
    }
    if (g_webviewController3) {
        g_webviewController3->Release();
        g_webviewController3 = nullptr;
    }
    if (g_webviewController) {
        g_webviewController->Close();
        g_webviewController->Release();
        g_webviewController = nullptr;
    }
    g_webviewReady = false;
    if (g_hWebView2Dll) {
        FreeLibrary(g_hWebView2Dll);
        g_hWebView2Dll = NULL;
    }
}

// ========== Window Procedure ==========

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_SIZE:
        if (wParam == SIZE_MINIMIZED) {
            // Minimize to tray if configured
            if (g_cfg.show_tray && strcmp(g_cfg.close_action, "minimize") == 0) {
                ShowWindow(hwnd, SW_HIDE);
                return 0;
            }
        }
        resize_webview();
        return 0;

    case WM_DPICHANGED:
        // Window moved to a monitor with different DPI
        // Always apply the system-suggested rect (required for Per-Monitor V2)
        {
            RECT *suggestedRect = (RECT *)lParam;
            SetWindowPos(hwnd, NULL,
                suggestedRect->left, suggestedRect->top,
                suggestedRect->right - suggestedRect->left,
                suggestedRect->bottom - suggestedRect->top,
                SWP_NOZORDER | SWP_NOACTIVATE);
            resize_webview();
        }
        return 0;

    case WM_CLOSE:
        if (strcmp(g_cfg.close_action, "minimize") == 0 && g_cfg.show_tray) {
            // Minimize to tray instead of closing
            ShowWindow(hwnd, SW_HIDE);
            return 0;
        }
        // Exit mode: destroy window
        DestroyWindow(hwnd);
        return 0;

    case WM_DESTROY:
        KillTimer(hwnd, TIMER_SERVER_WAIT);
        g_serverReady = false;
        g_navigated = false;
        destroy_webview();
        remove_tray_icon();
        PostQuitMessage(0);
        return 0;

    case WM_ENDSESSION:
        // System shutdown or user logoff - kill child process and exit quickly.
        // PostQuitMessage ensures the message loop exits, otherwise the app
        // keeps running until the system forcefully terminates it.
        if (wParam) {
            terminate_child();
            PostQuitMessage(0);
        }
        return 0;

    case WM_TRAYICON:
        if (LOWORD(lParam) == WM_LBUTTONDBLCLK) {
            // Double-click: show window
            ShowWindow(hwnd, SW_SHOW);
            SetForegroundWindow(hwnd);
        } else if (LOWORD(lParam) == WM_RBUTTONUP) {
            // Right-click: show context menu
            show_tray_menu(hwnd);
        }
        return 0;

    case WM_SHOWMAINWINDOW:
        // Another instance wants us to show our window
        ShowWindow(hwnd, SW_SHOW);
        if (IsIconic(hwnd)) {
            ShowWindow(hwnd, SW_RESTORE);
        }
        SetForegroundWindow(hwnd);
        return 0;

    case WM_TIMER:
        if (wParam == TIMER_SERVER_WAIT) {
            g_serverWaitCount++;

            // If already navigated or exiting, skip (pending WM_TIMER after KillTimer,
            // or during system shutdown after WM_ENDSESSION called terminate_child)
            if (g_navigated || g_exiting) return 0;

            // Check if child process has exited prematurely
            if (!is_child_running()) {
                KillTimer(hwnd, TIMER_SERVER_WAIT);
                DWORD exitCode = 0;
                GetExitCodeProcess(g_hChildProcess, &exitCode);
                char errMsg[512];
                snprintf(errMsg, sizeof(errMsg),
                    "Application process exited unexpectedly (code: 0x%08lX).\n\n"
                    "This may be caused by:\n"
                    "  - Port %d is already in use\n"
                    "  - Python module '%s' not found\n"
                    "  - Missing dependencies\n\n"
                    "Try running with --console for more details.",
                    exitCode, g_cfg.port, g_cfg.app_module);
                char msgTitle[256];
                snprintf(msgTitle, sizeof(msgTitle), "%s - Error", g_cfg.app_name);
                MessageBoxA(hwnd, errMsg, msgTitle, MB_ICONERROR);
                DestroyWindow(hwnd);
                return 0;
            }

            if (!g_serverReady && check_health(g_cfg.port)) {
                g_serverReady = true;
            }

            if (g_serverReady && g_webview) {
                // Both server and WebView2 are ready - navigate to the app
                g_navigated = true;
                KillTimer(hwnd, TIMER_SERVER_WAIT);
                WCHAR url[512];
                build_app_url(url, 512);
                g_webview->Navigate(url);
            } else if (g_serverWaitCount >= SERVER_WAIT_TIMEOUT_SEC * 1000 / TIMER_SERVER_INTERVAL_MS) {
                // Timeout - server or WebView2 didn't become ready
                KillTimer(hwnd, TIMER_SERVER_WAIT);
                char msgTitle[256];
                snprintf(msgTitle, sizeof(msgTitle), "%s - Error", g_cfg.app_name);
                MessageBoxA(hwnd,
                    "Failed to start application.\n\n"
                    "The server or UI did not become ready within 30 seconds.\n"
                    "Try running with --console for more details.",
                    msgTitle, MB_ICONERROR);
                DestroyWindow(hwnd);
            }
        }
        return 0;

    case WM_GETMINMAXINFO:
        // Handle window resizing limits
        if (!g_cfg.resizable) {
            MINMAXINFO *mmi = (MINMAXINFO *)lParam;
            mmi->ptMinTrackSize.x = g_cfg.width;
            mmi->ptMinTrackSize.y = g_cfg.height;
            mmi->ptMaxTrackSize.x = g_cfg.width;
            mmi->ptMaxTrackSize.y = g_cfg.height;
        }
        return 0;

    case WM_ERASEBKGND:
        if (!g_webviewReady) {
            // Draw gray background before WebView2 is ready (eliminates white flash)
            HDC hdc = (HDC)wParam;
            RECT rc;
            GetClientRect(hwnd, &rc);
            HBRUSH brush = CreateSolidBrush(RGB(245, 245, 245));
            FillRect(hdc, &rc, brush);
            DeleteObject(brush);
            return 1;
        }
        break;

    case WM_PAINT:
        if (!g_webviewReady) {
            // Draw native "Starting..." text before WebView2 is ready
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);
            RECT rc;
            GetClientRect(hwnd, &rc);

            // Draw text centered
            SetBkColor(hdc, RGB(245, 245, 245));
            SetTextColor(hdc, RGB(102, 102, 102));
            HFONT hFont = CreateFontA(18, 0, 0, 0, FW_NORMAL, 0, 0, 0,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, "Segoe UI");
            HFONT hOldFont = (HFONT)SelectObject(hdc, hFont);
            const char *text = "Starting...";
            DrawTextA(hdc, text, -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
            SelectObject(hdc, hOldFont);
            DeleteObject(hFont);

            EndPaint(hwnd, &ps);
            return 0;
        }
        break;
    }

    return DefWindowProcA(hwnd, msg, wParam, lParam);
}

// ========== Mode Runners ==========

// Forward declarations (for UI -> console fallback)
static int run_console_mode();
static int run_headless_mode();

static int run_ui_mode() {
    // 1. Register window class
    WNDCLASSEXA wc = {};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = WndProc;
    wc.hInstance = g_hInstance;
    // Load application icon from exe resources (set by rcedit --set-icon)
    // ExtractIconExA extracts both large and small icons from the exe,
    // using the same logic as Windows Explorer (resource ID independent)
    {
        char exePath[MAX_PATH];
        GetModuleFileNameA(NULL, exePath, MAX_PATH);
        HICON hIconLarge = NULL, hIconSmall = NULL;
        UINT count = ExtractIconExA(exePath, 0, &hIconLarge, &hIconSmall, 1);
        if (count > 0) {
            wc.hIcon = hIconLarge ? hIconLarge : LoadIcon(NULL, IDI_APPLICATION);
            wc.hIconSm = hIconSmall ? hIconSmall : LoadIcon(NULL, IDI_APPLICATION);
        } else {
            // No icon resource, use system defaults
            wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
            wc.hIconSm = LoadIcon(NULL, IDI_APPLICATION);
        }
    }
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = GetSysColorBrush(COLOR_BTNFACE);  // system brush, no need to delete
    wc.lpszClassName = g_wndClassName;
    RegisterClassExA(&wc);

    // 2. Create main window (show immediately for fast perceived startup)
    DWORD style = WS_OVERLAPPEDWINDOW;
    if (!g_cfg.resizable) {
        style &= ~WS_THICKFRAME;
        style &= ~WS_MAXIMIZEBOX;
    }

    g_hWnd = CreateWindowA(
        g_wndClassName, g_cfg.title,
        style,
        CW_USEDEFAULT, CW_USEDEFAULT,
        g_cfg.width, g_cfg.height,
        NULL, NULL, g_hInstance, NULL);

    if (!g_hWnd) {
        return 1;
    }

    // 2.5 Explicitly set window icons via WM_SETICON (most reliable method)
    // This overrides the class icon and ensures both title bar and taskbar show the correct icon
    {
        char exePath[MAX_PATH];
        GetModuleFileNameA(NULL, exePath, MAX_PATH);
        HICON hIconLarge = NULL, hIconSmall = NULL;
        UINT count = ExtractIconExA(exePath, 0, &hIconLarge, &hIconSmall, 1);
        if (count > 0) {
            if (hIconLarge) {
                SendMessage(g_hWnd, WM_SETICON, ICON_BIG, (LPARAM)hIconLarge);
            }
            if (hIconSmall) {
                SendMessage(g_hWnd, WM_SETICON, ICON_SMALL, (LPARAM)hIconSmall);
            }
        }
    }

    // 3. Show window immediately
    ShowWindow(g_hWnd, SW_SHOW);
    UpdateWindow(g_hWnd);

    // 4. Create WebView2 with loading page
    if (!create_webview()) {
        // WebView2 creation failed, fall back to console mode
        DestroyWindow(g_hWnd);
        g_hWnd = NULL;
        strncpy(g_cfg.mode, "console", sizeof(g_cfg.mode) - 1);
        g_cfg.mode[sizeof(g_cfg.mode) - 1] = '\0';
        return run_console_mode();
    }

    // 5. Create tray icon
    if (g_cfg.show_tray) {
        create_tray_icon(g_hWnd);
    }

    // 6. Start timer to poll for server readiness
    // The WebView2 currently shows a loading page.
    // Once the server is ready, the timer handler will navigate to the app URL.
    g_serverWaitCount = 0;
    g_serverReady = false;
    g_navigated = false;
    SetTimer(g_hWnd, TIMER_SERVER_WAIT, TIMER_SERVER_INTERVAL_MS, NULL);

    // 7. Message loop
    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    return (int)msg.wParam;
}

static int run_console_mode() {
    // Console mode: just wait for the child process
    WaitForSingleObject(g_hChildProcess, INFINITE);

    DWORD exitCode = 0;
    GetExitCodeProcess(g_hChildProcess, &exitCode);

    if (exitCode != 0 && exitCode != 1 && exitCode != 0xC000013A) {
        fprintf(stderr, "\nApplication exited unexpectedly (code: 0x%08lX)\n", exitCode);
    }

    if (g_cfg.pause_on_exit) {
        printf("\nPress Enter to exit...");
        getchar();
    }

    return (int)exitCode;
}

static int run_headless_mode() {
    // Headless mode: wait for child process, no window
    WaitForSingleObject(g_hChildProcess, INFINITE);

    DWORD exitCode = 0;
    GetExitCodeProcess(g_hChildProcess, &exitCode);
    return (int)exitCode;
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow) {
    g_hInstance = hInstance;

    // 1. Get exe directory (needed early for config parsing)
    char exePath[MAX_PATH];
    GetModuleFileNameA(NULL, exePath, MAX_PATH);
    strncpy(g_exeDir, exePath, MAX_PATH - 1);
    g_exeDir[MAX_PATH - 1] = '\0';
    char *lastSlash = strrchr(g_exeDir, '\\');
    if (lastSlash) *lastSlash = '\0';

    // 2. Parse configuration (before single instance check, so mutex name is known)
    config_set_defaults(&g_cfg);
    config_parse_ini(g_exeDir, &g_cfg);
    config_build_dynamic_strings(&g_cfg);

    // 3. Single instance check
    g_hMutex = CreateMutexA(NULL, TRUE, g_mutexName);
    if (g_hMutex == NULL || GetLastError() == ERROR_ALREADY_EXISTS) {
        if (g_hMutex) CloseHandle(g_hMutex);

        // Try to find and activate the existing window
        HWND existingWnd = FindWindowA(g_wndClassName, NULL);
        if (existingWnd) {
            // Window found - activate it
            PostMessage(existingWnd, WM_SHOWMAINWINDOW, 0, 0);
            SetForegroundWindow(existingWnd);
            return 0;
        }

        // Window not found but Mutex exists - previous instance may be shutting down,
        // or running in console/headless mode (which has no window to find).
        // Wait for the Mutex to be released (up to 2 seconds).
        HANDLE hWait = OpenMutexA(SYNCHRONIZE, FALSE, g_mutexName);
        if (hWait) {
            WaitForSingleObject(hWait, 2000);
            CloseHandle(hWait);
        }

        // Try again - previous instance should have exited by now
        g_hMutex = CreateMutexA(NULL, TRUE, g_mutexName);
        if (g_hMutex == NULL || GetLastError() == ERROR_ALREADY_EXISTS) {
            if (g_hMutex) CloseHandle(g_hMutex);
            MessageBoxA(NULL,
                "Application is already running.\n\nCheck the system tray or task manager.",
                g_cfg.app_name, MB_OK | MB_ICONINFORMATION);
            return 0;
        }
        // Mutex acquired - previous instance has exited, we can proceed
    }

    // 4. Parse command line arguments
    config_parse_args(&g_cfg);

    // 5. Enable Per-Monitor DPI Awareness V2 (before creating any window)
    // This ensures the app renders crisply on high-DPI displays.
    {
        HMODULE hUser32 = GetModuleHandleA("user32.dll");
        if (hUser32) {
            typedef BOOL (WINAPI *PFN_SetProcessDpiAwarenessContext)(HANDLE);
            auto pfn = (PFN_SetProcessDpiAwarenessContext)GetProcAddress(
                hUser32, "SetProcessDpiAwarenessContext");
            if (pfn) {
                // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ((DPI_CONTEXT_HANDLE)-4)
                pfn((HANDLE)-4);
            }
        }
    }

    // 6. Initialize COM (needed for WebView2)
    HRESULT hr = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    if (FAILED(hr)) {
        // COM init failed, force console mode
        strncpy(g_cfg.mode, "console", sizeof(g_cfg.mode) - 1);
        g_cfg.mode[sizeof(g_cfg.mode) - 1] = '\0';
    }

    // 7. Install console ctrl handler (prevent orphan processes)
    // This must be done BEFORE starting the child process,
    // so that Ctrl+C / shutdown signals are caught.
    install_ctrl_handler();

    // 8. Clean up leftover server on the port (defensive check)
    // If a previous instance crashed without releasing the port,
    // try to shut down the orphan server before starting a new one.
    if (check_health(g_cfg.port, 500)) {
        send_shutdown_request(g_cfg.port);
        // Wait for the server to stop responding to health checks
        for (int i = 0; i < 10; i++) {
            if (!check_health(g_cfg.port, 500)) break;
            Sleep(250);
        }
    }

    // Wait for the port to be available for binding.
    // Without SO_REUSEADDR, a port in TIME_WAIT will fail this check,
    // but uvicorn with reuse_address=True can still bind to it.
    // This loop mainly catches the case where the old server is slow to exit.
    for (int i = 0; i < 12; i++) {  // up to 3 seconds
        if (is_port_available(g_cfg.port)) break;
        Sleep(250);
    }

    if (!is_port_available(g_cfg.port)) {
        char msg[256];
        snprintf(msg, sizeof(msg),
            "Port %d is still in use. The application may fail to start.",
            g_cfg.port);
        char msgTitle[256];
        snprintf(msgTitle, sizeof(msgTitle), "%s - Warning", g_cfg.app_name);
        MessageBoxA(NULL, msg, msgTitle, MB_ICONWARNING);
    }

    // 9. Start Python child process
    if (!start_child_process()) {
        ReleaseMutex(g_hMutex);
        CloseHandle(g_hMutex);
        CoUninitialize();
        return 1;
    }

    // 10. Run in selected mode
    int result;
    if (strcmp(g_cfg.mode, "ui") == 0) {
        result = run_ui_mode();
        // WebView2 async failure may have changed mode to "console".
        // The async callback posts WM_CLOSE which exits the message loop,
        // but run_ui_mode() returns without falling back to console mode.
        if (strcmp(g_cfg.mode, "console") == 0) {
            result = run_console_mode();
        }
    } else if (strcmp(g_cfg.mode, "console") == 0) {
        result = run_console_mode();
    } else {
        result = run_headless_mode();
    }

    // 11. Cleanup
    // IMPORTANT: terminate_child() MUST complete before releasing the Mutex.
    // Otherwise a new instance could start while the old child process
    // is still holding the port, causing a port conflict crash.
    terminate_child();
    CoUninitialize();

    ReleaseMutex(g_hMutex);
    CloseHandle(g_hMutex);
    g_hMutex = NULL;

    return result;
}
