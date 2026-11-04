// Bytebeat Viewer - native Windows player for one compiled-in bytebeat.
// Evaluates the formula with an embedded QuickJS engine (same JS semantics as
// the dollchan bytebeat composer), plays it through waveOut, and draws the
// "Combined" view (waveform over diagram) into a 1024x256 pixel canvas.
//
// Keys: Space = pause/resume, R = restart, Up/Down = volume,
//       Left/Right = zoom (draw scale), F11 = fullscreen, Esc = quit.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

extern "C" {
#include "quickjs.h"
}
#include "song.h"

// ---------------------------------------------------------------- constants
static const int OUT_RATE = 48000;
static const int BLOCK_FRAMES = 1024;
static const int NUM_BLOCKS = 6;
static const int CW = 1024, CH = 256;              // canvas size (as dollchan)
static const uint8_t COL_WAVE[3] = {255, 255, 255}; // #ffffff
static const uint8_t COL_DIAG[3] = {0, 128, 255};   // #0080ff
static const uint8_t COL_CURSOR[3] = {128, 187, 255};// #80bbff
static const int CHAN[3] = {1, 0, 2};               // stereo colours: L=G, R=R+B

// ---------------------------------------------------------------- JS engine
struct Engine {
    JSRuntime *rt = nullptr;
    JSContext *ctx = nullptr;
    JSValue func = JS_UNDEFINED;
    JSValue global = JS_UNDEFINED;
    bool funcbeat = false;
    double sampleRate = 8000;
    std::string error;
    unsigned calls = 0;
    std::string runtimeError; // first runtime error (shown like dollchan)

    static std::string exc(JSContext *ctx) {
        JSValue e = JS_GetException(ctx);
        const char *s = JS_ToCString(ctx, e);
        std::string r = s ? s : "unknown error";
        if (s) JS_FreeCString(ctx, s);
        JS_FreeValue(ctx, e);
        return r;
    }

    bool init(const char *code, int mode, double sr) {
        funcbeat = mode == 3;
        sampleRate = sr;
        rt = JS_NewRuntime();
        JS_SetMaxStackSize(rt, 4 * 1024 * 1024);
        ctx = JS_NewContext(rt);
        global = JS_GetGlobalObject(ctx);
        static const char *builder =
            "(function(code, isFunc){\n"
            " var pre = 'var { ' + Object.getOwnPropertyNames(Math).filter(function(n){return n!=='constructor';}).join(', ') +\n"
            "   ' } = Math; var int = Math.trunc; var window = globalThis;';\n"
            " if (isFunc) return new Function(pre + 'return (function() {\\n' + code + '}).call(globalThis);')();\n"
            " code = code.trim().replace(/^eval\\(unescape\\(escape(?:`|\\('|\\(\"|\\(`)(.*?)(?:`|'\\)|\"\\)|`\\)).replace\\(\\/u\\(\\.\\.\\)\\/g,[\"'`]\\$1%[\"'`]\\)\\)\\)$/,\n"
            "   function(m, s){ return unescape(escape(s).replace(/u(..)/g, '$1%')); });\n"
            " return new Function('t', pre + 'return (function(t) { return 0,\\n' + (code || 0) + '}).call(globalThis, t);');\n"
            "})";
        JSValue b = JS_Eval(ctx, builder, strlen(builder), "<builder>", JS_EVAL_TYPE_GLOBAL);
        if (JS_IsException(b)) { error = exc(ctx); return false; }
        JSValue args[2] = {JS_NewString(ctx, code), JS_NewBool(ctx, funcbeat)};
        func = JS_Call(ctx, b, JS_UNDEFINED, 2, args);
        JS_FreeValue(ctx, args[0]);
        JS_FreeValue(ctx, b);
        if (JS_IsException(func)) { error = "compilation error: " + exc(ctx); func = JS_UNDEFINED; return false; }
        if (!JS_IsFunction(ctx, func)) {
            error = funcbeat ? "Funcbeat code must return a function!" : "code did not compile to a function";
            return false;
        }
        return true;
    }

    // Returns [L, R] raw values (NaN on error)
    void eval(double t, double &l, double &r) {
        JSValue res;
        if (funcbeat) {
            JSValue a[2] = {JS_NewFloat64(ctx, t / sampleRate), JS_NewFloat64(ctx, sampleRate)};
            res = JS_Call(ctx, func, global, 2, a);
        } else {
            JSValue a = JS_NewFloat64(ctx, t);
            res = JS_Call(ctx, func, global, 1, &a);
        }
        if (JS_IsException(res)) {
            std::string m = exc(ctx);
            if (runtimeError.empty()) {
                char tb[64]; snprintf(tb, sizeof tb, "t=%.0f error: ", t);
                runtimeError = tb + m;
            }
            l = r = NAN;
            return;
        }
        if (JS_IsArray(ctx, res)) {
            JSValue v0 = JS_GetPropertyUint32(ctx, res, 0), v1 = JS_GetPropertyUint32(ctx, res, 1);
            if (JS_ToFloat64(ctx, &l, v0)) { JS_FreeValue(ctx, JS_GetException(ctx)); l = NAN; }
            if (JS_ToFloat64(ctx, &r, v1)) { JS_FreeValue(ctx, JS_GetException(ctx)); r = NAN; }
            JS_FreeValue(ctx, v0); JS_FreeValue(ctx, v1);
        } else {
            if (JS_ToFloat64(ctx, &l, res)) { JS_FreeValue(ctx, JS_GetException(ctx)); l = NAN; }
            r = l;
        }
        JS_FreeValue(ctx, res);
        if ((++calls & 0x3FFF) == 0) JS_RunGC(rt); // keep memory flat for formulas that allocate
    }
};

// ---------------------------------------------------------------- shared state
struct DrawEntry { double t; float l, r; };
static const size_t RING = 1 << 19;
static DrawEntry g_ring[RING];
static volatile LONG64 g_ringHead = 0;   // written by audio thread
static LONG64 g_ringTail = 0;            // read by UI thread
static CRITICAL_SECTION g_lock;

static HWAVEOUT g_wave = nullptr;
static HANDLE g_waveEvent = nullptr;
static WAVEHDR g_hdr[NUM_BLOCKS];
static int16_t g_buf[NUM_BLOCKS][BLOCK_FRAMES * 2];
static volatile bool g_quit = false, g_paused = false;
static volatile LONG g_restart = 0;
static volatile float g_volume = 0.5f;
static volatile LONG64 g_framesSubmitted = 0;  // output frames written since (re)start
static volatile LONG64 g_posBase = 0;          // waveOut sample position at (re)start

static Engine g_eng;
static std::string g_error;
static HWND g_hwnd;

// ---------------------------------------------------------------- audio generation
struct Gen {
    double audioSample = 0, sampleRatio, byteSample = 0, lastTime = -1;
    double outValue[2] = {0, 0};
    float lastByte[2] = {0, 0};
    int mode;

    double getValue(double v, int ch) { // Floatbeat / Funcbeat
        double s = v > 1 ? 1 : (v < -1 ? -1 : v);
        lastByte[ch] = (float)std::round(127.5 * (s + 1));
        return s;
    }
    // JS ToInt32-ish conversion for "& 255" on doubles
    static int64_t toInt(double v) {
        if (!std::isfinite(v)) return 0;
        double m = std::fmod(std::trunc(v), 4294967296.0);
        return (int64_t)m;
    }
    double getValueJS(double v, int ch) {
        if (mode <= 1) {
            int64_t i = toInt(mode == 1 ? v + 128 : v);
            int b = (int)(i & 255);
            lastByte[ch] = (float)b;
            return b / 127.5 - 1;
        }
        return getValue(v, ch);
    }

    void reset() { audioSample = 0; byteSample = 0; lastTime = -1; outValue[0] = outValue[1] = 0; }

    void fill(int16_t *out, int frames) {
        double u = sampleRatio * audioSample;
        for (int i = 0; i < frames; ++i) {
            u += sampleRatio;
            double s = std::floor(u);
            if (lastTime != s) {
                double e = std::floor(byteSample);
                double l, r;
                g_eng.eval(e, l, r);
                if (std::isnan(r)) lastByte[1] = NAN; else outValue[1] = getValueJS(r, 1);
                if (std::isnan(l)) lastByte[0] = NAN; else outValue[0] = getValueJS(l, 0);
                LONG64 h = g_ringHead;
                g_ring[h & (RING - 1)] = {e, lastByte[0], lastByte[1]};
                InterlockedExchange64(&g_ringHead, h + 1);
                byteSample += s - lastTime;
                lastTime = s;
            }
            float vol = g_volume;
            for (int c = 0; c < 2; ++c) {
                double v = outValue[c] * vol;
                v = v > 1 ? 1 : (v < -1 ? -1 : v);
                out[i * 2 + c] = (int16_t)std::lround(v * 32767);
            }
        }
        audioSample += frames;
    }
};
static Gen g_gen;

static DWORD WINAPI AudioThread(LPVOID) {
    JS_UpdateStackTop(g_eng.rt); // formula runs on this thread's stack
    for (int i = 0; i < NUM_BLOCKS; ++i) {
        g_hdr[i] = {};
        g_hdr[i].lpData = (LPSTR)g_buf[i];
        g_hdr[i].dwBufferLength = sizeof(g_buf[i]);
        waveOutPrepareHeader(g_wave, &g_hdr[i], sizeof(WAVEHDR));
        g_hdr[i].dwFlags |= WHDR_DONE;
    }
    while (!g_quit) {
        if (InterlockedExchange(&g_restart, 0)) {
            waveOutReset(g_wave);
            for (int i = 0; i < NUM_BLOCKS; ++i)
                while (!(g_hdr[i].dwFlags & WHDR_DONE)) Sleep(1);
            g_gen.reset();
            MMTIME mt = {TIME_SAMPLES};
            waveOutGetPosition(g_wave, &mt, sizeof(mt));
            EnterCriticalSection(&g_lock);
            g_posBase = mt.u.sample;
            g_framesSubmitted = 0;
            g_ringTail = g_ringHead;
            LeaveCriticalSection(&g_lock);
            PostMessage(g_hwnd, WM_USER + 1, 0, 0); // clear canvas
            if (g_paused) waveOutPause(g_wave);
        }
        bool wrote = false;
        for (int i = 0; i < NUM_BLOCKS; ++i) {
            if (g_hdr[i].dwFlags & WHDR_DONE) {
                g_gen.fill(g_buf[i], BLOCK_FRAMES);
                g_hdr[i].dwFlags &= ~WHDR_DONE;
                waveOutWrite(g_wave, &g_hdr[i], sizeof(WAVEHDR));
                g_framesSubmitted += BLOCK_FRAMES;
                wrote = true;
            }
        }
        if (!wrote) WaitForSingleObject(g_waveEvent, 20);
    }
    waveOutReset(g_wave);
    for (int i = 0; i < NUM_BLOCKS; ++i) waveOutUnprepareHeader(g_wave, &g_hdr[i], sizeof(WAVEHDR));
    return 0;
}

// ---------------------------------------------------------------- Combined-mode renderer
static uint8_t g_rgb[CH][CW][3];
static uint8_t g_p[CH][CW];          // 1 = waveform point, 2 = waveform line
static uint32_t g_dib[CH * CW];
static int g_scale = 0;              // draw scale 0 = 1x zoom (1 sample per pixel column)
static double g_lastColAbs = -1;
static float g_prevL = NAN, g_prevR = NAN;
static bool g_havePrev = false;
static double g_cursorX = 0;

static void ClearCanvas() {
    memset(g_rgb, 0, sizeof(g_rgb));
    memset(g_p, 0, sizeof(g_p));
    g_lastColAbs = -1;
    g_havePrev = false;
}

static inline int wrapX(double x) { int i = (int)std::fmod(x, (double)CW); return i < 0 ? i + CW : i; }

static void ClearColumn(int x) {
    for (int y = 0; y < CH; ++y) { g_rgb[y][x][0] = g_rgb[y][x][1] = g_rgb[y][x][2] = 0; g_p[y][x] = 0; }
}

static void DrawEntries(const DrawEntry *e, size_t n) {
    // stereo if any entry in this batch differs between channels
    bool stereo = false;
    for (size_t i = 0; i < n; ++i)
        if (e[i].l != e[i].r && !std::isnan(e[i].l) && !std::isnan(e[i].r)) { stereo = true; break; }
    const int chans = stereo ? 2 : 1;
    const double div = (double)(1 << g_scale);
    const uint8_t lineCol[3] = {(uint8_t)(COL_WAVE[0] * .65), (uint8_t)(COL_WAVE[1] * .65), (uint8_t)(COL_WAVE[2] * .65)};
    const int k = CHAN[0], Q = CHAN[1], Z = CHAN[2];

    for (size_t i = 0; i < n; ++i) {
        const DrawEntry &d = e[i];
        double colStart = std::floor(d.t / div);
        double colEnd = std::ceil((d.t + 1) / div);
        if (colEnd <= colStart) colEnd = colStart + 1;
        // first time the head enters a column, it is wiped (dollchan draws fresh image data)
        if (colStart > g_lastColAbs) {
            double from = std::max(g_lastColAbs + 1, colStart - CW + 1);
            if (g_lastColAbs < 0) from = colStart;
            for (double c = from; c <= colStart; ++c) ClearColumn(wrapX(c));
        }
        for (double c = colStart + 1; c < colEnd; ++c) if (c > g_lastColAbs) ClearColumn(wrapX(c));
        if (colEnd - 1 > g_lastColAbs) g_lastColAbs = colEnd - 1;

        int ncols = (int)std::min(colEnd - colStart, (double)CW);
        int x0 = wrapX(colStart);

        if (std::isnan(d.l) || std::isnan(d.r)) {
            for (int c = 0; c < ncols; ++c) {
                int x = (x0 + c) % CW;
                for (int y = 0; y < CH; ++y)
                    if (g_p[y][x] != 1 && !g_rgb[y][x][1] && !g_rgb[y][x][2]) {
                        g_rgb[y][x][0] = 100; g_rgb[y][x][1] = 0; g_rgb[y][x][2] = 0;
                    }
            }
            g_prevL = d.l; g_prevR = d.r; g_havePrev = true;
            continue;
        }

        int D = std::max(1, 256 >> g_scale);
        int Y = D * (int)std::fmod(d.t, div);

        for (int L = chans - 1; L >= 0; --L) {
            int v = (int)(L ? d.r : d.l);
            v = v < 0 ? 0 : (v > 255 ? 255 : v);
            // waveform points
            for (int c = 0; c < ncols; ++c) {
                int x = (x0 + c) % CW, y = 255 - v;
                g_p[y][x] = 1;
                uint8_t *px = g_rgb[y][x];
                if (stereo) {
                    if (L) { px[Q] = COL_WAVE[Q]; px[Z] = COL_WAVE[Z]; } else px[k] = COL_WAVE[k];
                } else { px[0] = COL_WAVE[0]; px[1] = COL_WAVE[1]; px[2] = COL_WAVE[2]; }
            }
            // waveform connecting line from previous value
            float pv = L ? g_prevR : g_prevL;
            if (g_havePrev && !std::isnan(pv)) {
                int prev = (int)pv, x = x0;
                int step = prev < v ? 1 : -1;
                for (int s = prev; s != v; s += step) {
                    int y = 255 - s;
                    if (y < 0 || y >= CH || g_p[y][x] == 1) continue;
                    g_p[y][x] = 2;
                    uint8_t *px = g_rgb[y][x];
                    if (stereo) {
                        if (L) { px[Q] = lineCol[Q]; px[Z] = lineCol[Z]; } else px[k] = lineCol[k];
                    } else { px[0] = lineCol[0]; px[1] = lineCol[1]; px[2] = lineCol[2]; }
                }
            }
            // diagram
            double f = (v & 255) / 256.0;
            uint8_t dc[3] = {(uint8_t)(f * COL_DIAG[0]), (uint8_t)(f * COL_DIAG[1]), (uint8_t)(f * COL_DIAG[2])};
            for (int c = 0; c < ncols; ++c) {
                int x = (x0 + c) % CW;
                for (int r = 0; r < D; ++r) {
                    int y = Y + r;
                    if (y >= CH || g_p[y][x]) continue;
                    uint8_t *px = g_rgb[y][x];
                    if (stereo) {
                        if (L) {
                            if (Q == 1) px[1] = dc[1];
                            if (Z == 2) px[2] = dc[2];
                            if (Q == 0) px[0] = dc[0];
                        } else px[k] = dc[k];
                    } else { px[0] = dc[0]; px[1] = dc[1]; px[2] = dc[2]; }
                }
            }
        }
        g_prevL = d.l; g_prevR = d.r; g_havePrev = true;
    }
}

// Consume entries up to the sample that is currently audible.
static void UpdateCanvas() {
    MMTIME mt = {TIME_SAMPLES};
    waveOutGetPosition(g_wave, &mt, sizeof(mt));
    EnterCriticalSection(&g_lock);
    LONG64 played = (LONG64)(DWORD)(mt.u.sample - (DWORD)g_posBase);
    if (played > g_framesSubmitted) played = g_framesSubmitted;
    double playedT = std::floor(played * g_gen.sampleRatio);
    LONG64 head = g_ringHead;
    if (head - g_ringTail > (LONG64)RING) g_ringTail = head - RING;
    std::vector<DrawEntry> batch;
    while (g_ringTail < head) {
        const DrawEntry &d = g_ring[g_ringTail & (RING - 1)];
        if (d.t > playedT) break;
        batch.push_back(d);
        ++g_ringTail;
    }
    LeaveCriticalSection(&g_lock);
    if (!batch.empty()) DrawEntries(batch.data(), batch.size());
    g_cursorX = std::fmod(playedT / (double)(1 << g_scale), (double)CW);
}

// ---------------------------------------------------------------- window
static bool g_fullscreen = false;
static WINDOWPLACEMENT g_wp = {sizeof(g_wp)};

static void ToggleFullscreen(HWND h) {
    DWORD style = GetWindowLong(h, GWL_STYLE);
    if (!g_fullscreen) {
        MONITORINFO mi = {sizeof(mi)};
        GetWindowPlacement(h, &g_wp);
        GetMonitorInfo(MonitorFromWindow(h, MONITOR_DEFAULTTOPRIMARY), &mi);
        SetWindowLong(h, GWL_STYLE, style & ~WS_OVERLAPPEDWINDOW);
        SetWindowPos(h, HWND_TOP, mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right - mi.rcMonitor.left,
                     mi.rcMonitor.bottom - mi.rcMonitor.top, SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
    } else {
        SetWindowLong(h, GWL_STYLE, style | WS_OVERLAPPEDWINDOW);
        SetWindowPlacement(h, &g_wp);
        SetWindowPos(h, nullptr, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
    }
    g_fullscreen = !g_fullscreen;
}

static void Paint(HWND h) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(h, &ps);
    RECT rc; GetClientRect(h, &rc);
    int W = rc.right, H = rc.bottom;

    for (int y = 0; y < CH; ++y)
        for (int x = 0; x < CW; ++x) {
            const uint8_t *p = g_rgb[y][x];
            g_dib[y * CW + x] = (p[0] << 16) | (p[1] << 8) | p[2];
        }
    if (((double)g_gen.sampleRatio * OUT_RATE / (1 << g_scale)) < 2000) { // dollchan shows the cursor in this case
        int cx = (int)g_cursorX;
        for (int y = 0; y < CH; ++y)
            g_dib[y * CW + cx] = (COL_CURSOR[0] << 16) | (COL_CURSOR[1] << 8) | COL_CURSOR[2];
    }

    // fit canvas keeping 4:1 aspect, black bars around
    int dw = W, dh = W / 4;
    if (dh > H) { dh = H; dw = H * 4; }
    int ox = (W - dw) / 2, oy = (H - dh) / 2;

    HDC mem = CreateCompatibleDC(dc);
    HBITMAP bmp = CreateCompatibleBitmap(dc, W, H);
    HGDIOBJ old = SelectObject(mem, bmp);
    RECT all = {0, 0, W, H};
    FillRect(mem, &all, (HBRUSH)GetStockObject(BLACK_BRUSH));
    BITMAPINFO bi = {};
    bi.bmiHeader.biSize = sizeof(bi.bmiHeader);
    bi.bmiHeader.biWidth = CW;
    bi.bmiHeader.biHeight = -CH;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    SetStretchBltMode(mem, COLORONCOLOR);
    StretchDIBits(mem, ox, oy, dw, dh, 0, 0, CW, CH, g_dib, &bi, DIB_RGB_COLORS, SRCCOPY);

    if (g_error.empty() && !g_eng.runtimeError.empty()) g_error = g_eng.runtimeError;
    if (!g_error.empty() || g_paused) {
        SetBkMode(mem, TRANSPARENT);
        SetTextColor(mem, g_error.empty() ? RGB(250, 202, 99) : RGB(255, 90, 90));
        std::string msg = g_error.empty() ? "paused (space to resume)" : g_error;
        RECT tr = {8, 8, W - 8, H - 8};
        DrawTextA(mem, msg.c_str(), -1, &tr, DT_LEFT | DT_TOP | DT_WORDBREAK);
    }
    BitBlt(dc, 0, 0, W, H, mem, 0, 0, SRCCOPY);
    SelectObject(mem, old);
    DeleteObject(bmp);
    DeleteDC(mem);
    EndPaint(h, &ps);
}

static void UpdateTitle(HWND h) {
    char buf[256];
    double secs = g_gen.byteSample / SONG_RATE;
    snprintf(buf, sizeof buf, "%s  -  %dHz  -  t=%.0f  (%d:%02d)  vol %d%%%s", SONG_TITLE, (int)SONG_RATE,
             g_gen.byteSample, (int)secs / 60, (int)secs % 60, (int)std::lround(g_volume * 100),
             g_paused ? "  [paused]" : "");
    SetWindowTextA(h, buf);
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_TIMER:
        if (g_wave && !g_paused) UpdateCanvas();
        UpdateTitle(h);
        InvalidateRect(h, nullptr, FALSE);
        return 0;
    case WM_USER + 1: ClearCanvas(); return 0;
    case WM_ERASEBKGND: return 1;
    case WM_PAINT: Paint(h); return 0;
    case WM_KEYDOWN:
        switch (w) {
        case VK_SPACE:
            if (!g_wave) break;
            g_paused = !g_paused;
            if (g_paused) waveOutPause(g_wave); else waveOutRestart(g_wave);
            break;
        case 'R': InterlockedExchange(&g_restart, 1); SetEvent(g_waveEvent); break;
        case VK_UP: g_volume = std::min(1.0f, g_volume + 0.05f); break;
        case VK_DOWN: g_volume = std::max(0.0f, g_volume - 0.05f); break;
        case VK_LEFT: if (g_scale < 20) { ++g_scale; ClearCanvas(); } break;
        case VK_RIGHT: if (g_scale > 0) { --g_scale; ClearCanvas(); } break;
        case VK_F11: ToggleFullscreen(h); break;
        case VK_ESCAPE: if (g_fullscreen) ToggleFullscreen(h); else DestroyWindow(h); break;
        }
        return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProc(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE, LPSTR, int show) {
    InitializeCriticalSection(&g_lock);
    timeBeginPeriod(1);

    WNDCLASSA wc = {};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hIcon = LoadIcon(inst, MAKEINTRESOURCE(1));
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    wc.lpszClassName = "BytebeatViewer";
    RegisterClassA(&wc);
    RECT r = {0, 0, CW, CH};
    AdjustWindowRect(&r, WS_OVERLAPPEDWINDOW, FALSE);
    g_hwnd = CreateWindowA("BytebeatViewer", SONG_TITLE, WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
                           r.right - r.left, r.bottom - r.top, nullptr, nullptr, inst, nullptr);

    g_gen.mode = SONG_MODE;
    g_gen.sampleRatio = SONG_RATE / OUT_RATE;
    if (!g_eng.init(SONG_CODE, SONG_MODE, SONG_RATE)) {
        g_error = g_eng.error;
    } else {
        WAVEFORMATEX fmt = {};
        fmt.wFormatTag = WAVE_FORMAT_PCM;
        fmt.nChannels = 2;
        fmt.nSamplesPerSec = OUT_RATE;
        fmt.wBitsPerSample = 16;
        fmt.nBlockAlign = 4;
        fmt.nAvgBytesPerSec = OUT_RATE * 4;
        g_waveEvent = CreateEvent(nullptr, FALSE, FALSE, nullptr);
        if (waveOutOpen(&g_wave, WAVE_MAPPER, &fmt, (DWORD_PTR)g_waveEvent, 0, CALLBACK_EVENT) != MMSYSERR_NOERROR) {
            g_error = "could not open audio output";
            g_wave = nullptr;
        } else {
            CreateThread(nullptr, 0, AudioThread, nullptr, 0, nullptr);
        }
    }

    ShowWindow(g_hwnd, show);
    SetTimer(g_hwnd, 1, 16, nullptr);
    MSG msg;
    while (GetMessage(&msg, nullptr, 0, 0)) { TranslateMessage(&msg); DispatchMessage(&msg); }
    g_quit = true;
    if (g_waveEvent) SetEvent(g_waveEvent);
    Sleep(50);
    if (g_wave) waveOutClose(g_wave);
    timeEndPeriod(1);
    return 0;
}
