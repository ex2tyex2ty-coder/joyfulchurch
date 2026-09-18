/* Private Supabase Broadcast. Bodies remain behind server-side authorization. */
class SoundRealtime {
  constructor(config, emit) {
    this.config=config; this.emit=emit; this.stopped=false; this.paused=false;
    this.seq=0; this.changes=0; this.ref=0; this.attempts=0; this.timers=new Set(); this.status='';
    this.client=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  }
  later(fn, ms) {
    const id=setTimeout(()=>{this.timers.delete(id); if(!this.stopped) fn();},ms);
    this.timers.add(id); return id;
  }
  cancel(name) {clearTimeout(this[name]);this.timers.delete(this[name]);this[name]=null;}
  signal(status) {
    if(this.stopped) return;
    this.status=status;
    if(status==='changed') this.changes++;
    this.emit({status,client:this.client,seq:++this.seq,changes:this.changes,scope:this.config.scope,token:this.session?.access_token || ''});
  }
  async start() {
    if(this.stopped || this.paused || this.starting) return;
    if(!this.config.url || !this.config.api_key) {this.signal('fallback');return;}
    this.starting=true; this.waitingAuth=true; this.disconnect(); this.cancel('retryTimer');
    try {
      this.storageKey='joyful.sound.auth.'+this.config.url;
      if(!this.loaded) {
        this.loaded=true;
        try {this.session=JSON.parse(sessionStorage.getItem(this.storageKey)||'null');} catch(_) {}
      }
      if(!this.session?.access_token || !Number.isFinite(this.session.expires_at) || this.session.expires_at*1000 < Date.now()+90000) await this.authenticate();
      if(this.stopped || this.paused) return;
      this.signal('auth'); this.scheduleRefresh();
      this.cancel('authTimer');
      this.authTimer=this.later(()=>this.start(),30000);
    } catch(_) {this.signal('offline');this.retry(true);}
    finally {this.starting=false;}
  }
  async authenticate() {
    const refresh=this.session?.refresh_token;
    const response=await fetch(this.config.url+'/auth/v1/'+(refresh?'token?grant_type=refresh_token':'signup'), {
      method:'POST',headers:{apikey:this.config.api_key,'Content-Type':'application/json'},
      body:JSON.stringify(refresh?{refresh_token:refresh}:{}),signal:AbortSignal.timeout(10000)
    });
    if(!response.ok) {
      if(refresh && [400,401,403].includes(response.status)) {
        this.session=null;
        try {sessionStorage.removeItem(this.storageKey);} catch(_) {}
      }
      throw new Error('auth');
    }
    const data=await response.json();
    if(!data.access_token || !data.refresh_token) throw new Error('auth');
    if(this.stopped) return;
    this.session={access_token:data.access_token,refresh_token:data.refresh_token,
      expires_at:data.expires_at || Math.floor(Date.now()/1000)+data.expires_in};
    try {sessionStorage.setItem(this.storageKey,JSON.stringify(this.session));} catch(_) {}
  }
  scheduleRefresh() {
    this.cancel('refreshTimer');
    this.refreshTimer=this.later(()=>this.start(),Math.max(1000,this.session.expires_at*1000-Date.now()-60000));
  }
  authorize(args) {
    if(this.stopped || this.paused || !this.session || args.accepted_token!==this.session.access_token || !args.topic) return;
    if(args.expires*1000<=Date.now()) return;
    this.waitingAuth=false;this.cancel('authTimer');
    if(this.topic!==args.topic) this.disconnect();
    this.topic=args.topic;this.expires=args.expires;
    this.cancel('expiryTimer');
    this.expiryTimer=this.later(()=>this.start(),this.expires*1000-Date.now());
    if(!this.retryTimer) this.connect();
  }
  send(event,payload={},topic='realtime:'+this.topic,ref=String(++this.ref)) {
    if(this.socket?.readyState===1) this.socket.send(JSON.stringify({topic,event,payload,ref,join_ref:this.joinRef}));
    return ref;
  }
  retry(auth=false) {
    this.cancel('retryTimer');
    if(this.stopped || this.paused) return;
    const delay=Math.min(30000,1000*2**Math.min(this.attempts++,5));
    this.retryTimer=this.later(()=>{this.retryTimer=null;auth?this.start():this.connect();},delay);
  }
  connect() {
    if(this.stopped || this.paused || this.socket || this.waitingAuth || !this.topic) return;
    if(this.session.expires_at*1000<=Date.now()+10000 || this.expires*1000<=Date.now()) {this.start();return;}
    const url=this.config.url.replace('https://','wss://')+'/realtime/v1/websocket?apikey='+encodeURIComponent(this.config.api_key)+'&vsn=1.0.0';
    let ws;
    try {ws=new WebSocket(url);} catch(_) {this.signal('offline');this.retry();return;}
    this.socket=ws;
    const fail=(auth=false)=>{
      if(this.socket!==ws || this.stopped) return;
      this.disconnect();this.signal('offline');this.retry(auth);
    };
    ws.onopen=()=>{
      if(this.socket!==ws) return;
      this.joinRef=String(++this.ref);
      this.send('phx_join',{config:{private:true,broadcast:{ack:false,self:false},presence:{enabled:false},postgres_changes:[]},access_token:this.session.access_token},'realtime:'+this.topic,this.joinRef);
    };
    this.joinTimer=this.later(()=>fail(),12000);
    ws.onmessage=e=>{
      if(this.socket!==ws) return;
      let m;try {m=JSON.parse(e.data);} catch(_) {return;}
      if(m.event==='phx_reply' && m.ref===this.heartbeatRef) {
        this.cancel('heartbeatDeadline');this.heartbeatRef=null;
        if(m.payload?.status==='ok') this.signal('healthy');else fail();
        return;
      }
      if(m.topic!=='realtime:'+this.topic) return;
      if(m.event==='phx_reply' && m.ref===this.joinRef) {
        this.cancel('joinTimer');
        if(m.payload?.status!=='ok') {fail(true);return;}
        this.attempts=0;this.signal('connected');this.heartbeat(fail);
      } else if(m.event==='broadcast' && m.payload?.event==='changed') {
        if(!this.changeTimer) this.changeTimer=this.later(()=>{this.changeTimer=null;this.signal('changed');},100);
      } else if(m.event==='phx_error' || m.event==='phx_close') fail(true);
    };
    ws.onerror=()=>fail();ws.onclose=()=>fail();
  }
  heartbeat(fail) {
    this.cancel('heartbeatTimer');
    this.heartbeatTimer=this.later(()=>{
      if(!this.socket) return;
      this.heartbeatRef=this.send('heartbeat',{},'phoenix');
      this.heartbeatDeadline=this.later(()=>fail(),8000);
      this.heartbeat(fail);
    },15000);
  }
  pause() {
    if(this.stopped) return;
    this.paused=true;this.disconnect();
    for(const name of ['retryTimer','authTimer','refreshTimer','expiryTimer']) this.cancel(name);
    this.signal('paused');
  }
  resume() {
    if(this.stopped) return;
    this.paused=false;this.signal('catchup');
    if(!this.socket || this.socket.readyState!==1 || this.expires*1000<=Date.now()+10000) this.start();
  }
  disconnect() {
    for(const name of ['joinTimer','heartbeatTimer','heartbeatDeadline','changeTimer']) this.cancel(name);
    this.heartbeatRef=null;
    const ws=this.socket;this.socket=null;
    if(ws) {ws.onopen=null;ws.onclose=null;ws.onerror=null;ws.onmessage=null;ws.close();}
  }
  stop() {this.stopped=true;this.disconnect();for(const id of this.timers) clearTimeout(id);this.timers.clear();}
}
if(typeof module!=='undefined') module.exports={SoundRealtime};
