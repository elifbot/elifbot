# Explicitly block external network for the offline test process; UNIX sockets
# (used by asyncio's internal wakeup pair) remain available.
import socket
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo

def guarded(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        raise OSError('offline benchmark: IP network disabled')
    return _orig_connect(self,address)

def guarded_ex(self,address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        raise OSError('offline benchmark: IP network disabled')
    return _orig_connect_ex(self,address)

def no_dns(*args,**kwargs):
    raise OSError('offline benchmark: DNS disabled')
socket.socket.connect=guarded
socket.socket.connect_ex=guarded_ex
socket.getaddrinfo=no_dns
_orig_sendto = socket.socket.sendto
def guarded_sendto(self, *args):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        raise OSError('offline benchmark: IP datagrams disabled')
    return _orig_sendto(self, *args)
socket.socket.sendto = guarded_sendto
if hasattr(socket.socket, 'sendmsg'):
    _orig_sendmsg = socket.socket.sendmsg
    def guarded_sendmsg(self, *args):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise OSError('offline benchmark: IP sendmsg disabled')
        return _orig_sendmsg(self, *args)
    socket.socket.sendmsg = guarded_sendmsg
