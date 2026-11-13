"""Local NTP guard: estimates current clock health, never changes system time.

Runs separate from the bot. NTP sources are not independently authenticated;
tracking uncertainty and past clock accuracy are not guaranteed.
"""
import ctypes
import os
import sys
import subprocess
import time
from datetime import datetime, timezone


def kernel_clock_status():
    # Read-only adjtimex(modes=0). Limit ABI assumptions and fail closed on
    # unsupported platforms; the buffer has ample room for the full struct.
    if sys.platform != 'linux' or ctypes.sizeof(ctypes.c_long) != 8:
        raise OSError('unsupported adjtimex ABI')
    class TimexHead(ctypes.Structure):
        _fields_=[('modes',ctypes.c_uint),('offset',ctypes.c_long),('freq',ctypes.c_long),
                  ('maxerror',ctypes.c_long),('esterror',ctypes.c_long),('status',ctypes.c_int),
                  ('remainder',ctypes.c_ubyte*512)]
    data=TimexHead()  # all zero, including modes: no clock changes
    libc=ctypes.CDLL(None,use_errno=True)
    call=libc.adjtimex;call.argtypes=[ctypes.c_void_p];call.restype=ctypes.c_int
    state=call(ctypes.byref(data))
    if state < 0:
        error=ctypes.get_errno();raise OSError(error,os.strerror(error))
    status=int(data.status)
    return {'state':state,'status':status,
            'synchronized':state != 5 and not (status & (0x40|0x1000))}


def sample(runner=subprocess.run, kernel_reader=kernel_clock_status):
    result={'utc':datetime.now(timezone.utc).isoformat(),'monotonic':time.monotonic(),'ok':False}
    try:
        sync=runner(['timedatectl','show','-p','NTPSynchronized','--value'],
                    capture_output=True,text=True,check=True,timeout=3).stdout.strip().lower()
        text=runner(['chronyc','-n','tracking'],capture_output=True,text=True,
                    check=True,timeout=3).stdout
        fields={}
        for line in text.splitlines():
            if ':' in line:
                key,value=line.split(':',1);fields[key.strip()]=value.strip()
        def seconds(name):
            value=fields[name].split()[0]
            v=float(value)
            if not 0 <= v < 1e5:raise ValueError(name)
            return v
        leap=fields.get('Leap status','')
        offset=seconds('System time'); delay=seconds('Root delay'); dispersion=seconds('Root dispersion')
        root_distance=offset+delay/2+dispersion
        kernel=kernel_reader()
        result.update({'timedatectl_synchronized':sync=='yes',
                       'kernel_synchronized':kernel['synchronized'],
                       'kernel_adjtimex_state':kernel['state'],
                       'kernel_adjtimex_status':kernel['status'], 'leap_status':leap,
                       'stratum':int(fields['Stratum']),'offset_s':offset,
                       'root_delay_s':delay,'root_dispersion_s':dispersion,
                       'estimated_bound_s':root_distance,
                       'ntp_controlled_by_systemd':False})
        result['ok']=(sync=='yes' and kernel['synchronized'] and leap=='Normal' and 0<result['stratum']<16 and root_distance<=.5)
    except (subprocess.SubprocessError,OSError,ValueError,KeyError,IndexError,AttributeError,TypeError) as exc:
        result['error_type']=type(exc).__name__
    return result
