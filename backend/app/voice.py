"""Separate telephone extension point. No real call capability is implemented.

A future provider must be connected and explicitly approved before implementing
call dispatch. The current module always reports its actual unavailable state.
"""

def status():
    return {'status': 'not_connected', 'label': 'Modulo telefonico predisposto, provider non collegato'}

class VoiceNotConnected(RuntimeError):
    pass

def start_call(*args, **kwargs):
    raise VoiceNotConnected('Telefonia non collegata: nessuna chiamata eseguita.')
