# Cheat Engine on turing-hv

Part of **[RingMinusOne-hv](https://github.com/RingMinusOne-hv)**: tools ported onto **turing-hv**, our hypervisor.

This is Cheat Engine 7.5 (upstream [cheat-engine/cheat-engine](https://github.com/cheat-engine/cheat-engine) master
`ec45d5f`) with a second memory backend: the turing-hv hypervisor. With the backend on, Cheat Engine reads and writes a
process through that process's own page tables, from underneath Windows. There is no `ReadProcessMemory`, no
`PROCESS_VM_*` handle, no kernel driver and no debug port, and nothing changes inside the target.

turing-hv itself is not public. Without it, this builds and runs as ordinary Cheat Engine: the backend is off until you
turn it on.

The full write-up is **[TURINGHV-PORT.md](TURINGHV-PORT.md)**: how it works, what was tested, and what the hypervisor
still lacks.

## What we did

**A memory backend that is the hypervisor.** `turinghvport.pas` swaps Cheat Engine's `NewKernelHandler` pointers, the
same seam upstream uses for ceserver and macOS. The swapped functions are `OpenProcess`, `ReadProcessMemory` /
`WriteProcessMemory`, `VirtualQueryEx`, Toolhelp and the psapi calls. The scanner, memory view, disassembler, pointer
scanner, structure dissect, address list, auto assembler and Lua all run on top of it unchanged.

**A trusted broker.** The hypervisor serves only programs it measured, running elevated, with no foreign or generated
code in them. Cheat Engine can't be one: it has about 2000 code pages, loads Lua and plugins, and file dialogs pull in
shell extensions. So a tiny C program, `thvbridge.exe` (about 25 code pages), is trusted instead. It is a
bounds-checked pass-through for the hypervisor's SDK. Cheat Engine talks to it over an unnamed, inherited shared
section, and all the policy stays in Pascal.

**Finding the right page tables, provably.** Opening a process runs a ladder until a page-table root checks out:

1. `EPROCESS.DirectoryTableBase`;
2. the hypervisor's CR3 tracker;
3. a CR3-write watch;
4. a sweep of physical memory.

A candidate root must translate the image base to a PE header and pass a PEB identity check, so a second copy of the
same game can't be confused with the first. A root found only by the sweep is used read-only. Once the process exits,
every access is refused, so a reused page table is never written.

**A debugger the game can't see.** Cheat Engine's own debugger runs on the hypervisor:

- **Breakpoints and stepping.** Toggle breakpoint, step into and over, run to cursor, change registers, and conditional
  breakpoints. The thread that hits a breakpoint is held by re-faulting its code page. There is no `int3`, no debug
  register and no debug port, and only that thread stops.
- **Find out what writes / accesses this address.** The hypervisor's data watch: exact counts per instruction, with the
  registers of each one's first hit.
- **Find out what addresses this instruction accesses.** The instruction watch.
- **Snapshot breakpoints.** A capture of every register, the stack and the code, without stopping the thread.
- **Native Break and Trace.** The hypervisor follows a thread one instruction at a time across pages. The thread never
  stops and never sees the trap flag.
- **Pause.** The hypervisor's freeze holds every thread of the game, with no suspend count.
- **Threads without handles.** Registers come from the debugger's snapshot or from the thread's kernel trap frame.
- **Call stack.** Decoded from the modules' own unwind tables.

**Lua.** `turinghv_*` functions cover the backend, raw CR3 and physical reads, the watches, breakpoints, the unwinder
and the hypervisor's log. The list is in TURINGHV-PORT.md §2.

**Turing Explorer.** `Cheat Engine\turinghv\build_turing_explorer.ps1` builds a rebranded copy of Cheat Engine from a
staged copy of the source; the repository itself is not changed. The copy has no Cheat Engine name or vocabulary in
anything it ships. That covers the process and window names, version info, registry and temp folders, strings, and
unit, class and form names. The icon is a purple version of Cheat Engine's. See TURINGHV-PORT.md §8.

## What still goes through Windows (or doesn't work)

The hypervisor writes only pages that are writable in the target's own page tables. These features need the opt-in
Windows fallback, which the game can see:

- code patching (NOPs, `jmp` hooks);
- `alloc` in auto assembler;
- remote threads.

Because of that, everything built on DLL injection doesn't work through the hypervisor: speedhack, the
Mono/.NET/Java data collectors and the D3D overlay. Pages that aren't present are invisible. Section 5 of
TURINGHV-PORT.md lists each gap and what the hypervisor would need to close it.

## Build, trust, run

```
cd "Cheat Engine"
C:\lazarus\lazbuild.exe -B --build-mode="Release 64-Bit" cheatengine.lpi
powershell -ExecutionPolicy Bypass -File turinghv\build_thvbridge.ps1
```

1. Build with Lazarus 2.2.2 / FPC 3.2.2, as upstream does. Always build with `-B`: incremental builds hit an FPC
   internal error.
2. `build_thvbridge.ps1` builds `bin\thvbridge.exe` and copies in the `turinghv.dll` of your hypervisor build.
3. Trust `bin\thvbridge.exe` with write access in the hypervisor. Do it again after every rebuild of the bridge.
4. Run Cheat Engine as administrator and pick **Turing-HV > Use the Turing-HV hypervisor as the memory backend**.

## Tests

- `Cheat Engine\turinghv\tests\run_tests.ps1` drives Cheat Engine through a Lua script against two targets with known
  memory, one x64 and one WOW64. It covers open, read, write, scans, modules, watches, the CR3 ladder, refusals after
  exit, and the menus.
- `run_debugger_test.ps1` covers the debugger.

On the last run, 105 and 44 checks passed with no failures, on the Turing Explorer build. The test target's
anti-debug checks reported no debugger and no integrity change.

---

*The upstream Cheat Engine README follows.*

<p align="center">
    <a href="https://github.com/cheat-engine/cheat-engine/raw/master/Cheat%20Engine/images">
        <img src="https://github.com/cheat-engine/cheat-engine/raw/master/Cheat%20Engine/images/celogo.png" />
    </a>
</p>

<h1 align="center">Cheat Engine</h1>

Cheat Engine is a development environment focused on modding games and applications for personal use.


# Download

  * **[Latest Version](https://github.com/cheat-engine/cheat-engine/releases/latest)**

[Older versions](https://github.com/cheat-engine/cheat-engine/releases)


# Links

  * [Website](https://www.cheatengine.org)
  * [Forum](https://forum.cheatengine.org)
  * [Forum (alternate)](https://opencheattables.com/)
  * [Forum (alternate)](https://fearlessrevolution.com/index.php)
  * [Wiki](https://wiki.cheatengine.org/index.php?title=Main_Page)

## Social Media

  * [Reddit](https://reddit.com/r/cheatengine)
  * [Twitter](https://twitter.com/_cheatengine)

## Donate

  * [Patreon](https://www.patreon.com/cheatengine)
  * [PayPal](https://www.paypal.com/xclick/business=dark_byte%40hotmail.com&no_note=1&tax=0&lc=US)


## Basic Build Instructions

  1. Download Lazarus 2.2.2 from https://sourceforge.net/projects/lazarus/files/Lazarus%20Windows%2064%20bits/Lazarus%202.2.2/ First install lazarus-2.2.2-fpc-3.2.2-win64.exe and then lazarus-2.2.2-fpc-3.2.2-cross-i386-win32-win64.exe
  
  2. Run Lazarus and click on `Project->Open Project`. Select `cheatengine.lpi` from the `Cheat Engine` folder as the project.
  3. Click on `Run->Build` or press <kbd>SHIFT+F9</kbd>.
      * you can also click on `Run->Compile many Modes` (tip: select first three compile modes)
      * If you want to run or debug from the IDE on Windows you will need to run Lazarus as administrator.
      
  Do not forget to compile secondary projects you'd like to use:
  
     speedhack.lpr: Compile both 32- and 64-bit DLL's for speedhack capability
     luaclient.lpr: Compile both 32- and 64-bit DLL's for {$luacode} capability
     DirectXMess.sln: Compile for 32-bit and 64-bit for D3D overlay and snapshot capabilities
     DotNetcompiler.sln: for the cscompile lua command
     monodatacollector.sln: Compile both 32-bit and 64-bit dll's to get Mono features to inspect the .NET environment of the process    
     dotnetdatacollector.sln: Compile both 32- and 64-bit EXE's to get .NET symbols
     dotnetinvasivedatacollector.sln: Compile this managed .DLL to add support for runtime JIT support
     cejvmti.sln: Compile both 32- and 64-bit DLL's for Java inspection support
     tcclib.sln: Compile 32-32, 64-32 and 64-64 to add {$C} and {$CCODE} support in scripts
     vehdebug.lpr: Compile 32- and 64-bit DLL's to add support for the VEH debugger interface
     dbkkernel.sln: for kernelmode functions (settings->extra) You will need to build the no-sig version and either boot with unsigned driver support, or sign the driver yourself    
    
*.SLN files require visual studio (Usually 2017)
