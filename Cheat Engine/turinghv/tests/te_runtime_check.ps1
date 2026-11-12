<#
    te_runtime_check.ps1 -- start Turing Explorer and look at it the way another program on the machine can: every
    window it owns (hidden and message-only ones too), the modules it loaded, its named kernel objects, the registry
    and temp folders it touched, and the words left in its memory (and the bridge's).

        powershell -ExecutionPolicy Bypass -File "Cheat Engine\turinghv\tests\te_runtime_check.ps1" [-Exe <path>] [-Wait 8]

    Run as administrator (the backend needs it).  The program is closed at the end.
#>
param([string]$Exe = 'C:\projs\turing-explorer\turing-explorer.exe', [int]$Wait = 8, [switch]$KeepOpen)
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class TeCheck {
    delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr p, EnumProc f, IntPtr l);
    [DllImport("user32.dll")] static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string title);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);

    static string Text(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
    static string Cls(IntPtr h) { var s = new StringBuilder(256); GetClassName(h, s, 256); return s.ToString(); }

    public static List<string> Windows(uint pid) {
        var r = new List<string>();
        EnumWindows((h, l) => {
            uint p; GetWindowThreadProcessId(h, out p);
            if (p == pid) {
                r.Add(String.Format("top   {0,-7} class={1,-28} title=\"{2}\"", IsWindowVisible(h) ? "shown" : "hidden", Cls(h), Text(h)));
                EnumChildWindows(h, (c, l2) => {
                    string t = Text(c);
                    if (t.Length > 0) r.Add(String.Format("child {0,-7} class={1,-28} text=\"{2}\"", IsWindowVisible(c) ? "shown" : "hidden", Cls(c), t.Length > 80 ? t.Substring(0, 80) : t));
                    return true;
                }, IntPtr.Zero);
            }
            return true;
        }, IntPtr.Zero);
        IntPtr HWND_MESSAGE = new IntPtr(-3), w = IntPtr.Zero;
        while ((w = FindWindowEx(HWND_MESSAGE, w, null, null)) != IntPtr.Zero) {
            uint p; GetWindowThreadProcessId(w, out p);
            if (p == pid) r.Add(String.Format("msg   {0,-7} class={1,-28} title=\"{2}\"", "-", Cls(w), Text(w)));
        }
        return r;
    }

    // ---- memory
    [StructLayout(LayoutKind.Sequential)] struct MBI { public IntPtr Base, AllocBase; public uint AllocProt; public IntPtr Size; public uint State, Protect, Type; }
    [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint a, bool i, uint pid);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll")] static extern IntPtr VirtualQueryEx(IntPtr p, IntPtr a, out MBI m, IntPtr n);
    [DllImport("kernel32.dll")] static extern bool ReadProcessMemory(IntPtr p, IntPtr a, byte[] b, IntPtr n, out IntPtr got);

    public static List<string> Memory(uint pid, string[] words, int samples) {
        var r = new List<string>();
        IntPtr ph = OpenProcess(0x0410, false, pid);
        if (ph == IntPtr.Zero) { r.Add("cannot open the process"); return r; }
        var counts = new Dictionary<string, int>();
        var shown = new Dictionary<string, int>();
        long addr = 0, scanned = 0;
        MBI m;
        while (VirtualQueryEx(ph, new IntPtr(addr), out m, new IntPtr(Marshal.SizeOf(typeof(MBI)))) != IntPtr.Zero) {
            long size = m.Size.ToInt64();
            if (m.State == 0x1000 && (m.Protect & 0x101) == 0 && (m.Protect & 0xEE) != 0 && size < (512L << 20)) {
                var buf = new byte[size];
                IntPtr got;
                if (ReadProcessMemory(ph, m.Base, buf, m.Size, out got) && got.ToInt64() > 0) {
                    scanned += got.ToInt64();
                    for (int i = 0; i < buf.Length; i++) { byte c = buf[i]; if (c >= 65 && c <= 90) buf[i] = (byte)(c + 32); }
                    string kind = m.Type == 0x1000000 ? "image" : m.Type == 0x40000 ? "mapped" : "private";
                    foreach (var w in words) {
                        foreach (var utf16 in new[] { false, true }) {
                            byte[] pat = utf16 ? Encoding.Unicode.GetBytes(w) : Encoding.ASCII.GetBytes(w);
                            int at = 0;
                            while ((at = IndexOf(buf, pat, at)) >= 0) {
                                string key = w + (utf16 ? " (utf-16)" : "");
                                counts[key] = (counts.ContainsKey(key) ? counts[key] : 0) + 1;
                                int s = shown.ContainsKey(key) ? shown[key] : 0;
                                if (s < samples) {
                                    shown[key] = s + 1;
                                    int a = Math.Max(0, at - 48), b = Math.Min(buf.Length, at + pat.Length + 48);
                                    var sb = new StringBuilder();
                                    for (int k = a; k < b; k++) { byte c = buf[k]; if (utf16 && c == 0) continue; sb.Append(c >= 32 && c < 127 ? (char)c : '.'); }
                                    r.Add(String.Format("  [{0}] {1} @{2:x}: {3}", key, kind, m.Base.ToInt64() + at, sb));
                                }
                                at += pat.Length;
                            }
                        }
                    }
                }
            }
            addr = m.Base.ToInt64() + size;
            if (addr <= 0) break;
        }
        CloseHandle(ph);
        var summary = new StringBuilder(String.Format("memory: {0:N0} MB scanned;", scanned >> 20));
        if (counts.Count == 0) summary.Append(" no hits");
        foreach (var kv in counts) summary.Append(String.Format(" {0}={1}", kv.Key, kv.Value));
        r.Insert(0, summary.ToString());
        return r;
    }

    static int IndexOf(byte[] b, byte[] p, int from) {
        int last = b.Length - p.Length;
        byte f = p[0];
        for (int i = from; i <= last; i++) {
            if (b[i] != f) { i = Array.IndexOf(b, f, i + 1); if (i < 0 || i > last) return -1; }
            int k = 1;
            while (k < p.Length && b[i + k] == p[k]) k++;
            if (k == p.Length) return i;
        }
        return -1;
    }

    // ---- named handles
    [DllImport("ntdll.dll")] static extern int NtQuerySystemInformation(int c, IntPtr b, int n, out int need);
    [DllImport("ntdll.dll")] static extern int NtQueryObject(IntPtr h, int c, IntPtr b, int n, out int need);
    [DllImport("kernel32.dll")] static extern bool DuplicateHandle(IntPtr sp, IntPtr sh, IntPtr tp, out IntPtr th, uint a, bool i, uint o);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern uint GetFileType(IntPtr h);

    static string ObjString(IntPtr h, int cls) {
        IntPtr b = Marshal.AllocHGlobal(0x2000);
        try {
            int need;
            if (NtQueryObject(h, cls, b, 0x2000, out need) != 0) return null;
            ushort len = (ushort)Marshal.ReadInt16(b);
            IntPtr s = Marshal.ReadIntPtr(b, IntPtr.Size);
            return len == 0 || s == IntPtr.Zero ? "" : Marshal.PtrToStringUni(s, len / 2);
        } finally { Marshal.FreeHGlobal(b); }
    }

    public static List<string> Handles(uint pid) {
        var r = new List<string>();
        int size = 1 << 22, need;
        IntPtr buf = Marshal.AllocHGlobal(size);
        while (NtQuerySystemInformation(64, buf, size, out need) == unchecked((int)0xC0000004)) {
            Marshal.FreeHGlobal(buf); size = Math.Max(need + (1 << 20), size * 2); buf = Marshal.AllocHGlobal(size);
        }
        long n = Marshal.ReadInt64(buf);
        IntPtr ph = OpenProcess(0x40, false, pid);       // PROCESS_DUP_HANDLE
        int entry = IntPtr.Size == 8 ? 40 : 28;
        for (long i = 0; i < n; i++) {
            IntPtr e = new IntPtr(buf.ToInt64() + 16 + i * entry);
            long owner = Marshal.ReadInt64(e, 8);
            if (owner != pid) continue;
            long hv = Marshal.ReadInt64(e, 16);
            IntPtr dup;
            if (!DuplicateHandle(ph, new IntPtr(hv), GetCurrentProcess(), out dup, 0, false, 2)) continue;
            string type = ObjString(dup, 2);
            string name = null;
            if (type == "File") { if (GetFileType(dup) == 1) name = ObjString(dup, 1); }      // disk files only (pipes can hang)
            else name = ObjString(dup, 1);
            CloseHandle(dup);
            if (!String.IsNullOrEmpty(name)) r.Add(String.Format("{0,-12} {1}", type, name));
        }
        CloseHandle(ph);
        Marshal.FreeHGlobal(buf);
        return r;
    }
}
'@

$words = 'cheat engine', 'cheatengine', 'cheat-engine', 'dark byte', 'darkbyte', 'cheat table', 'dbk32', 'dbk64', 'dbvm',
         'ultimap', 'speedhack', 'd3dhook', 'vehdebug', 'cetrainer', 'ceserver', 'celua', 'cepack', 'runtime modifier'
function Hit($s) { foreach ($w in $words) { if ($s -match [regex]::Escape($w)) { return $true } }; return $false }

$tempBefore = @(Get-ChildItem $env:TEMP -Force -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
$exeName = [IO.Path]::GetFileNameWithoutExtension($Exe)
Get-Process $exeName -ErrorAction SilentlyContinue | Stop-Process -Force
$p = Start-Process -FilePath $Exe -WorkingDirectory (Split-Path $Exe) -PassThru
Start-Sleep -Seconds $Wait
$p.Refresh()
if ($p.HasExited) { Write-Host "the program exited (code $($p.ExitCode))" -ForegroundColor Red; exit 1 }

Write-Host "== process: $($p.ProcessName) pid $($p.Id)  $($p.Path)"
Write-Host "   main window title: '$($p.MainWindowTitle)'"
$cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)"
Write-Host "   command line: $($cim.CommandLine)"
$vi = (Get-Item $Exe).VersionInfo
Write-Host "   version info: $($vi.CompanyName) | $($vi.ProductName) | $($vi.FileDescription) | $($vi.OriginalFilename) | $($vi.InternalName) | $($vi.FileVersion)"
$kids = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)")
foreach ($k in $kids) { Write-Host "   child: $($k.Name) pid $($k.ProcessId)  $($k.CommandLine)" }

Write-Host '== windows'
$wins = [TeCheck]::Windows([uint32]$p.Id)
foreach ($w in $wins) { Write-Host ("   " + $w) -ForegroundColor ($(if (Hit $w) { 'Red' } else { 'Gray' })) }

Write-Host '== modules'
foreach ($m in $p.Modules) {
    if ($m.FileName -notlike "$env:windir\*") { Write-Host ("   " + $m.FileName) -ForegroundColor ($(if (Hit $m.FileName) { 'Red' } else { 'Gray' })) }
}
Write-Host ("   (+ {0} modules from {1})" -f @($p.Modules | Where-Object { $_.FileName -like "$env:windir\*" }).Count, $env:windir)

Write-Host '== named objects'
$hs = [TeCheck]::Handles([uint32]$p.Id)
foreach ($h in $hs) { if ((Hit $h) -or $h -notmatch '^(Key|File|Directory)\s') { Write-Host ("   " + $h) -ForegroundColor ($(if (Hit $h) { 'Red' } else { 'Gray' })) } }
Write-Host ("   ({0} named handles; keys/files/directories listed only when they hold a word)" -f $hs.Count)
foreach ($h in $hs) { if (($h -match '^(Key|File|Directory)\s') -and -not (Hit $h)) { } }

Write-Host '== registry'
foreach ($k in 'HKCU:\Software\Turing Explorer', 'HKCU:\Software\Cheat Engine') {
    if (Test-Path $k) { Write-Host "   $k exists ($(@((Get-Item $k).Property).Count) values)" } else { Write-Host "   $k absent" }
}

Write-Host '== memory (the program)'
foreach ($l in [TeCheck]::Memory([uint32]$p.Id, $words, 3)) { Write-Host ("   " + $l) }
foreach ($k in $kids) {
    Write-Host "== memory ($($k.Name))"
    foreach ($l in [TeCheck]::Memory([uint32]$k.ProcessId, $words, 3)) { Write-Host ("   " + $l) }
}

if (-not $KeepOpen) {
    $null = $p.CloseMainWindow()
    if (-not $p.WaitForExit(8000)) { Stop-Process -Id $p.Id -Force }
    Start-Sleep -Milliseconds 500
}
Write-Host '== temp folder (new or holding a word)'
$tempAfter = @(Get-ChildItem $env:TEMP -Force -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
foreach ($t in $tempAfter) {
    $new = $tempBefore -notcontains $t
    if ($new) { Write-Host "   new: $t" -ForegroundColor ($(if (Hit $t) { 'Red' } else { 'Gray' })) }
    elseif (Hit $t) { Write-Host "   (there before this run: $t)" -ForegroundColor DarkYellow }
}
