/* Native Supabase protocol v1. No DB polling, external script or message bodies. */
class SoundRealtime {
  constructor(config, emit) {
    this.config=config; this.emit=emit; this.stopped=false; this.seq=0;
    this.ref=0; this.attempts=0; this.timers=new Set(); this.status='';
  }
  later(fn, ms) {
    const id=setTimeout(()=>{this.timers.delete(id); if(!this.stopped) fn();},ms);
    this.timers.add(id); return id;
  }
  signal(status) {
    if(this.stopped) return;
    this.status=status;
    this.emit({status,seq:++this.seq,scope:this.config.scope,token:this.session?.access_token || ''});
  }
  async start() {
    try {
      this.storageKey='joyful.sound.auth.'+this.config.url;
      try { this.session=JSON.parse(sessionStorage.getItem(this.storageKey)||'null'); } catch(_) {}
      if (!this.session || this.session.expires_at*1000 < Date.now()+90000) await this.authenticate();
      if(this.stopped) return;
      this.signal('auth'); this.scheduleRefresh();
    } catch(_) { this.signal('error'); }
  }
  async authenticate() {
    const refresh=this.session?.refresh_token;
    const response=await fetch(this.config.url+'/auth/v1/'+(refresh?'token?grant_type=refresh_token':'signup'), {
      method:'POST',headers:{apikey:this.config.api_key,'Content-Type':'application/json'},
      body:JSON.stringify(refresh?{refresh_token:refresh}:{}),signal:AbortSignal.timeout(10000)
    });
    if(!response.ok) throw new Error('auth');
    const data=await response.json();
    if(!data.access_token || !data.refresh_token) throw new Error('auth');
    if(this.stopped) return;
    this.session={access_token:data.access_token,refresh_token:data.refresh_token,
      expires_at:data.expires_at || Math.floor(Date.now()/1000)+data.expires_in};
    try { sessionStorage.setItem(this.storageKey,JSON.stringify(this.session)); } catch(_) {}
  }
  scheduleRefresh() {
    clearTimeout(this.refreshTimer);
    this.refreshTimer=this.later(async()=>{
      try { await this.authenticate(); if(this.stopped) return;
        this.disconnect(); this.signal('auth'); this.scheduleRefresh();
      } catch(_) { this.signal('error'); }
    },Math.max(1000,this.session.expires_at*1000-Date.now()-60000));
  }
  authorize(args) {
    this.args=args;
    if(!this.session || args.accepted_token !== this.session.access_token || !args.topic) return;
    if(this.socket && this.topic===args.topic && this.socket.readyState<=1) return;
    this.topic=args.topic; this.expires=args.expires;
    if(this.expires*1000<=Date.now()) {this.signal('expired');return;}
    clearTimeout(this.expiryTimer);
    this.expiryTimer=this.later(()=>{this.disconnect();this.signal('expired');},this.expires*1000-Date.now());
    this.connect();
  }
  send(event,payload={},topic='realtime:'+this.topic,ref=String(++this.ref)) {
    if(this.socket?.readyState===1) this.socket.send(JSON.stringify({topic,event,payload,ref,join_ref:this.joinRef}));
    return ref;
  }
  connect() {
    if(this.stopped || this.socket || this.status==='error') return;
    const url=this.config.url.replace('https://','wss://')+'/realtime/v1/websocket?apikey='+encodeURIComponent(this.config.api_key)+'&vsn=1.0.0';
    const ws=new WebSocket(url); this.socket=ws;
    const fail=()=>{
      if(this.socket!==ws || this.stopped) return;
      this.disconnect(); this.signal('offline');
      if(++this.attempts>6) {this.signal('error');return;}
      this.later(()=>this.connect(),Math.min(30000,1000*2**(this.attempts-1)));
    };
    ws.onopen=()=>{
      if(this.socket!==ws) return;
      this.joinRef=String(++this.ref);
      this.send('phx_join',{config:{private:true,broadcast:{ack:false,self:false},presence:{enabled:false},postgres_changes:[]},access_token:this.session.access_token},'realtime:'+this.topic,this.joinRef);
    };
    this.joinTimer=this.later(fail,12000);
    ws.onmessage=e=>{
      if(this.socket!==ws) return;
      let m; try {m=JSON.parse(e.data);} catch(_) {return;}
      if(m.event==='phx_reply' && m.ref===this.heartbeatRef) {
        clearTimeout(this.heartbeatDeadline); this.heartbeatRef=null; return;
      }
      if(m.topic!=='realtime:'+this.topic) return;
      if(m.event==='phx_reply' && m.ref===this.joinRef) {
        clearTimeout(this.joinTimer);
        if(m.payload.status!=='ok') {this.disconnect();this.signal('error');return;}
        this.attempts=0; this.signal('connected'); this.heartbeat(fail);
      } else if(m.event==='broadcast' && m.payload?.event==='changed') {
        // Collapse duplicate notifications from request + reply in one transaction.
        if(!this.changeTimer) this.changeTimer=this.later(()=>{this.changeTimer=null;this.signal('changed');},150);
      } else if(m.event==='phx_error' || m.event==='phx_close') fail();
    };
    ws.onerror=fail; ws.onclose=fail;
  }
  heartbeat(fail) {
    clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer=this.later(()=>{
      if(!this.socket) return;
      this.heartbeatRef=this.send('heartbeat',{},'phoenix');
      this.heartbeatDeadline=this.later(fail,10000);
      this.heartbeat(fail);
    },25000); // Socket keepalive only: no database read or Streamlit rerun.
  }
  resume() {
    if(this.stopped) return;
    if(this.expires && this.expires*1000<=Date.now()) {this.disconnect();this.signal('expired');return;}
    if(this.session && this.session.expires_at*1000<Date.now()+60000) {
      this.start(); return;
    }
    // A visible tab catches up once; it never starts a polling timer.
    if(this.socket?.readyState===1) this.signal('changed');
    else if(this.topic && this.status!=='error') this.connect();
  }
  disconnect() {
    for(const name of ['joinTimer','heartbeatTimer','heartbeatDeadline','changeTimer']) clearTimeout(this[name]);
    this.changeTimer=null;
    const ws=this.socket; this.socket=null;
    if(ws) {ws.onclose=null;ws.onerror=null;ws.onmessage=null;ws.close();}
  }
  stop() {this.stopped=true;this.disconnect();for(const id of this.timers) clearTimeout(id);this.timers.clear();}
}
if(typeof module!=='undefined') module.exports={SoundRealtime};
