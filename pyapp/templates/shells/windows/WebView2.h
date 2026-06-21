/**
 * WebView2 API Declarations (Minimal)
 *
 * Derived from Microsoft Edge WebView2 SDK.
 * https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/
 *
 * This is a minimal subset of the WebView2 Win32 C API, containing only the
 * interfaces needed for the PyApp launcher stub. It allows compilation without
 * the full WebView2 SDK NuGet package.
 *
 * WebView2Loader.dll is loaded at runtime via LoadLibrary + GetProcAddress,
 * so no import library is needed at link time.
 *
 * License: BSD-3-Clause (https://learn.microsoft.com/en-us/legal/windows-sdk/msdkredist)
 */

#ifndef __WEBVIEW2_H_INCLUDED__
#define __WEBVIEW2_H_INCLUDED__

#include <windows.h>
#include <objbase.h>

// EventRegistrationToken definition (from eventtoken.h)
#ifndef _EVENTREGISTRATIONTOKEN_DEFINED
#define _EVENTREGISTRATIONTOKEN_DEFINED
typedef struct _EventRegistrationToken {
    __int64 value;
} EventRegistrationToken;
#endif

// Forward declarations
interface ICoreWebView2;
interface ICoreWebView2Controller;
interface ICoreWebView2Environment;
interface ICoreWebView2Settings;

// ===== Callback interfaces =====

// GUID definitions for MinGW compatibility
// {4E8A4986-5B6D-4068-925C-4F3E0E5A2771}
DEFINE_GUID(IID_ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler,
    0x4E8A4986, 0x5B6D, 0x4068, 0x92, 0x5C, 0x4F, 0x3E, 0x0E, 0x5A, 0x27, 0x71);

// {630481FC-3F8D-49E2-8D7D-56B8B062E2A0}
DEFINE_GUID(IID_ICoreWebView2CreateCoreWebView2ControllerCompletedHandler,
    0x630481FC, 0x3F8D, 0x49E2, 0x8D, 0x7D, 0x56, 0xB8, 0xB0, 0x62, 0xE2, 0xA0);

class ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler : public IUnknown
{
public:
    virtual HRESULT STDMETHODCALLTYPE Invoke(
        HRESULT result,
        ICoreWebView2Environment *createdEnvironment) = 0;
};

class ICoreWebView2CreateCoreWebView2ControllerCompletedHandler : public IUnknown
{
public:
    virtual HRESULT STDMETHODCALLTYPE Invoke(
        HRESULT result,
        ICoreWebView2Controller *createdController) = 0;
};

// ===== Core interfaces =====

class ICoreWebView2 : public IUnknown
{
public:
    virtual HRESULT STDMETHODCALLTYPE get_Settings(
        ICoreWebView2Settings **settings) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_Source(
        LPWSTR *uri) = 0;
    virtual HRESULT STDMETHODCALLTYPE Navigate(
        LPCWSTR uri) = 0;
    virtual HRESULT STDMETHODCALLTYPE NavigateToString(
        LPCWSTR htmlContent) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_NavigationStarting(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_NavigationStarting(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_NavigationCompleted(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_NavigationCompleted(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_FrameNavigationStarting(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_FrameNavigationStarting(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_FrameNavigationCompleted(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_FrameNavigationCompleted(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_WindowCloseRequested(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_WindowCloseRequested(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE AddScriptToExecuteOnDocumentCreated(
        LPCWSTR javaScript,
        IUnknown *handler) = 0;
    virtual HRESULT STDMETHODCALLTYPE RemoveScriptToExecuteOnDocumentCreated(
        LPCWSTR id) = 0;
    virtual HRESULT STDMETHODCALLTYPE ExecuteScript(
        LPCWSTR javaScript,
        IUnknown *handler) = 0;
    virtual HRESULT STDMETHODCALLTYPE CapturePreview(
        int imageFormat,
        IUnknown *imageStream,
        IUnknown *handler) = 0;
    virtual HRESULT STDMETHODCALLTYPE Reload() = 0;
    virtual HRESULT STDMETHODCALLTYPE PostWebMessageAsJson(
        LPCWSTR webMessageAsJson) = 0;
    virtual HRESULT STDMETHODCALLTYPE PostWebMessageAsString(
        LPCWSTR webMessageAsString) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_WebMessageReceived(
        IUnknown *handler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_WebMessageReceived(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE CallDevToolsProtocolMethod(
        LPCWSTR methodName,
        LPCWSTR parametersAsJson,
        IUnknown *handler) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_BrowserProcessId(
        UINT32 *value) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_CanGoBack(
        BOOL *value) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_CanGoForward(
        BOOL *value) = 0;
    virtual HRESULT STDMETHODCALLTYPE GoBack() = 0;
    virtual HRESULT STDMETHODCALLTYPE GoForward() = 0;
    virtual HRESULT STDMETHODCALLTYPE GetDevToolsProtocolEventReceiver(
        LPCWSTR eventName,
        IUnknown **receiver) = 0;
    virtual HRESULT STDMETHODCALLTYPE Stop() = 0;
    virtual HRESULT STDMETHODCALLTYPE add_NewWindowRequested(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_NewWindowRequested(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_DocumentTitleChanged(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_DocumentTitleChanged(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_DocumentTitle(
        LPWSTR *title) = 0;
    virtual HRESULT STDMETHODCALLTYPE AddHostObjectToScript(
        LPCWSTR name,
        VARIANT *object,
        IUnknown **jsonConverter) = 0;
    virtual HRESULT STDMETHODCALLTYPE RemoveHostObjectFromScript(
        LPCWSTR name) = 0;
    virtual HRESULT STDMETHODCALLTYPE OpenDevToolsWindow() = 0;
    virtual HRESULT STDMETHODCALLTYPE add_ContainsFullScreenElementChanged(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_ContainsFullScreenElementChanged(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_ContainsFullScreenElement(
        BOOL *value) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_WebResourceRequested(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_WebResourceRequested(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE AddWebResourceRequestedFilter(
        LPCWSTR uri,
        int resourceContext) = 0;
    virtual HRESULT STDMETHODCALLTYPE RemoveWebResourceRequestedFilter(
        LPCWSTR uri,
        int resourceContext) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_WebResourceResponseReceived(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_WebResourceResponseReceived(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE CallDevToolsProtocolMethodForSession(
        LPCWSTR sessionId,
        LPCWSTR methodName,
        LPCWSTR parametersAsJson,
        IUnknown *handler) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_UserAgent(
        LPWSTR *value) = 0;
};

class ICoreWebView2Controller : public IUnknown
{
public:
    virtual HRESULT STDMETHODCALLTYPE get_IsVisible(
        BOOL *isVisible) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsVisible(
        BOOL isVisible) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_Bounds(
        RECT *bounds) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_Bounds(
        RECT bounds) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_ZoomFactor(
        double *zoomFactor) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_ZoomFactor(
        double zoomFactor) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_ZoomFactorChanged(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_ZoomFactorChanged(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetBoundsAndZoomFactor(
        RECT bounds,
        double zoomFactor) = 0;
    virtual HRESULT STDMETHODCALLTYPE MoveFocus(
        int reason) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_MoveFocusRequested(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_MoveFocusRequested(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_GotFocus(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_GotFocus(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_LostFocus(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_LostFocus(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE add_AcceleratorKeyPressed(
        IUnknown *eventHandler,
        EventRegistrationToken *token) = 0;
    virtual HRESULT STDMETHODCALLTYPE remove_AcceleratorKeyPressed(
        EventRegistrationToken token) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_ParentWindow(
        HWND *parentWindow) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_ParentWindow(
        HWND parentWindow) = 0;
    virtual HRESULT STDMETHODCALLTYPE NotifyParentWindowPositionChanged() = 0;
    virtual HRESULT STDMETHODCALLTYPE Close() = 0;
    virtual HRESULT STDMETHODCALLTYPE get_CoreWebView2(
        ICoreWebView2 **coreWebView2) = 0;
};

class ICoreWebView2Environment : public IUnknown
{
public:
    virtual HRESULT STDMETHODCALLTYPE CreateCoreWebView2Controller(
        HWND parentWindow,
        ICoreWebView2CreateCoreWebView2ControllerCompletedHandler *handler) = 0;
    virtual HRESULT STDMETHODCALLTYPE CreateWebResourceResponse(
        IUnknown *stream,
        int statusCode,
        LPCWSTR reasonPhrase,
        LPCWSTR headers,
        IUnknown **response) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_BrowserProcessId(
        UINT32 *value) = 0;
};

class ICoreWebView2Settings : public IUnknown
{
public:
    virtual HRESULT STDMETHODCALLTYPE get_IsScriptEnabled(
        BOOL *isScriptEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsScriptEnabled(
        BOOL isScriptEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsWebMessageEnabled(
        BOOL *isWebMessageEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsWebMessageEnabled(
        BOOL isWebMessageEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_AreDefaultScriptDialogsEnabled(
        BOOL *areDefaultScriptDialogsEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_AreDefaultScriptDialogsEnabled(
        BOOL areDefaultScriptDialogsEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsStatusBarEnabled(
        BOOL *isStatusBarEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsStatusBarEnabled(
        BOOL isStatusBarEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_AreDevToolsEnabled(
        BOOL *areDevToolsEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_AreDevToolsEnabled(
        BOOL areDevToolsEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsDefaultBackgroundEnabled(
        BOOL *isDefaultBackgroundEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsDefaultBackgroundEnabled(
        BOOL isDefaultBackgroundEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsZoomControlEnabled(
        BOOL *isZoomControlEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsZoomControlEnabled(
        BOOL isZoomControlEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE get_IsBuiltInErrorPageEnabled(
        BOOL *isEnabled) = 0;
    virtual HRESULT STDMETHODCALLTYPE put_IsBuiltInErrorPageEnabled(
        BOOL isEnabled) = 0;
};

// ===== Factory function type (for runtime dynamic loading) =====

typedef HRESULT (WINAPI *PFNCreateCoreWebView2EnvironmentWithOptions)(
    LPCWSTR browserDirPath,
    LPCWSTR userDataFolder,
    IUnknown *environmentOptions,
    ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *environmentCreatedHandler);

typedef HRESULT (WINAPI *PFNCreateCoreWebView2Environment)(
    ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler *environmentCreatedHandler);

#endif // __WEBVIEW2_H_INCLUDED__
