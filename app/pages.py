"""HTML pages: landing, privacy, terms, thanks, admin, simulator."""
import html
import io
import urllib.parse

from .config import settings

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#2C2C2A;background:#FBF8F3;line-height:1.6}
.wrap{max-width:760px;margin:0 auto;padding:32px 20px}h1{font-size:34px;line-height:1.2;margin:.2em 0}h2{margin-top:1.6em}
.btn{display:inline-block;background:#128C7E;color:#fff;padding:14px 22px;border-radius:10px;text-decoration:none;font-weight:600}
.muted{color:#6b6a65}.card{background:#fff;border:1px solid #e8e3da;border-radius:14px;padding:18px 20px;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.stat{background:#fff;border:1px solid #e8e3da;border-radius:12px;padding:12px 14px}
.stat b{font-size:22px;display:block}
"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class="wrap">{body}</div></body></html>"""


def wa_link(text: str = "Hi Dinner 101") -> str:
    return f"https://wa.me/{settings.wa_display_number}?text={urllib.parse.quote(text)}"


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def landing() -> str:
    link = wa_link()
    return _page("Dinner 101 - what's for dinner, sorted", f"""
<p class="muted">Dinner 101</p>
<h1>What's for dinner? Sorted, on WhatsApp.</h1>
<p>Every afternoon Dinner 101 sends you <b>one dinner idea</b> made from what's already in your kitchen, and uses up food before it goes off.</p>
<p><a class="btn" href="{link}">Start on WhatsApp</a></p>
<p class="muted">{settings.trial_days} days free, then R{settings.price_rands:.0f}/month. Cancel any time.</p>
<div class="card"><h3>How it works</h3>
<ol><li><b>Send a voice note</b> of what's in your kitchen. Walk around and talk.</li>
<li><b>Snap your till slip</b> after shopping, or send a voice note of what you bought.</li>
<li><b>Get tonight's dinner</b> on WhatsApp with a photo. Tap "Let's cook it".</li>
<li><b>See what you saved</b> every month, in Rand.</li></ol></div>
<div class="card" style="text-align:center"><p>Scan to start on WhatsApp</p><div style="width:200px;margin:0 auto">{qr_svg(link)}</div></div>
<p class="muted" style="margin-top:40px"><a href="/privacy">Privacy policy</a> · <a href="/terms">Terms</a></p>
""")


def privacy() -> str:
    return _page("Privacy policy - Dinner 101", """
<h1>Privacy policy</h1><p class="muted">DRAFT - have this reviewed before launch.</p>
<p>Dinner 101 is operated by Pips to Profit (Pty) Ltd ("we"). We respect your privacy and process personal information in line with the Protection of Personal Information Act (POPIA).</p>
<h2>What we collect</h2><ul><li>Your WhatsApp number and WhatsApp profile name.</li>
<li>Photos of till slips, voice notes and messages you send us, and the kitchen items, quantities and prices we read from them.</li>
<li>Your dinner choices and replies (e.g. "Cooked it").</li><li>Subscription status. Card payments are handled by PayFast; we never see or store card numbers.</li></ul>
<h2>Why</h2><p>Only to run the service: keep your kitchen list, suggest dinners, show your savings, and bill your subscription.</p>
<h2>Who we share with</h2><p>Service providers that help run Dinner 101: Meta (WhatsApp), our AI providers (to read slips and voice notes), our hosting provider and PayFast. We don't sell your information.</p>
<h2>How long we keep it</h2><p>While you use Dinner 101. Slip photos and voice notes are deleted once processed. Send "delete my data" and we'll delete your account within 30 days.</p>
<h2>Your rights</h2><p>You can ask to see, correct or delete your information. Contact: [email address]. You may also complain to the Information Regulator of South Africa.</p>
""")


def terms() -> str:
    return _page("Terms - Dinner 101", f"""
<h1>Terms of use</h1><p class="muted">DRAFT - have this reviewed before launch.</p>
<ul><li>Dinner 101 gives meal ideas based on what you tell us is in your kitchen. Always check food is fresh and safe before cooking, and check recipes for allergies.</li>
<li>Free trial for {settings.trial_days} days, then R{settings.price_rands:.0f} per month, billed monthly through PayFast until you cancel.</li>
<li>Cancel any time by sending "cancel" on WhatsApp. You won't be billed again; no refunds for part months.</li>
<li>We may change prices with 30 days' notice on WhatsApp.</li>
<li>Operated by Pips to Profit (Pty) Ltd, South Africa.</li></ul>""")


def thanks() -> str:
    return _page("Thank you", """<h1>You're subscribed 🎉</h1><p>Head back to WhatsApp. Tonight's dinner idea will arrive as usual.</p>""")


def subscribe_placeholder() -> str:
    return _page("Subscribe", """<h1>Payments are not switched on yet</h1><p>PayFast details still need to be added (see README).</p>""")


def admin(data: dict, key: str) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(u['phone'])}</td><td>{html.escape(u['name'] or '')}</td><td>{u['stage']}</td><td>{u['status']}</td>"
        f"<td>{u['items']}</td><td>{u['dinners']}</td><td>{u['cooked']}</td><td>R{u['saved']:.0f}</td><td>${u['cost']:.2f}</td></tr>"
        for u in data["users"])
    fails = "".join(f"<tr><td>{f['at']}</td><td>{f['kind']}</td><td>{html.escape(f['raw'] or '')[:80]}</td><td>{html.escape(f['error'] or '')[:120]}</td></tr>"
                    for f in data["failures"])
    costs = "".join(f"<tr><td>{k}</td><td>{v['n']}</td><td>${v['usd']:.2f}</td></tr>" for k, v in data["costs"].items())
    return _page("Dinner 101 admin", f"""
<h1>Dinner 101 admin</h1>
<div class="grid">
<div class="stat"><span class="muted">Households</span><b>{data['n_users']}</b></div>
<div class="stat"><span class="muted">Paying</span><b>{data['n_active']}</b></div>
<div class="stat"><span class="muted">On trial</span><b>{data['n_trial']}</b></div>
<div class="stat"><span class="muted">Cost / household / month</span><b>R{data['cost_per_user_zar']:.2f}</b></div>
<div class="stat"><span class="muted">Revenue / month</span><b>R{data['revenue']:.0f}</b></div>
</div>
<h2>Costs, last 30 days</h2><table><tr><th>Kind</th><th>Count</th><th>USD</th></tr>{costs}</table>
<h2>Households</h2><table><tr><th>Phone</th><th>Name</th><th>Stage</th><th>Status</th><th>Items</th><th>Dinners</th><th>Cooked</th><th>Saved</th><th>Cost 30d</th></tr>{rows}</table>
<h2>Couldn't read</h2><table><tr><th>When</th><th>Kind</th><th>Input</th><th>Error</th></tr>{fails}</table>
<h2>Tools</h2>
<form method="post" action="/admin/generate-photos?key={html.escape(key)}"><button class="btn" style="border:0">Generate missing recipe photos</button></form>
<p class="muted">Photos made: {data['photos']} of {data['recipes']} recipes.</p>
""")


SIMULATOR = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dinner 101 simulator</title><style>
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f3f0ea;color:#2C2C2A}
.layout{display:flex;gap:24px;justify-content:center;padding:24px;flex-wrap:wrap}
.phone{width:380px;height:760px;border:10px solid #2C2C2A;border-radius:34px;overflow:hidden;display:flex;flex-direction:column;background:#EFE7DD}
.top{background:#075E54;color:#fff;padding:12px 14px;display:flex;gap:10px;align-items:center}
.av{width:36px;height:36px;border-radius:50%;background:#FAEEDA;color:#633806;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600}
.chat{flex:1;overflow-y:auto;padding:12px 10px}
.in{background:#fff;border-radius:0 10px 10px 10px;padding:8px 10px;margin:6px 0;max-width:290px;white-space:pre-wrap;font-size:14px}
.out{background:#D9FDD3;border-radius:10px 0 10px 10px;padding:8px 10px;margin:6px 0 6px auto;max-width:290px;white-space:pre-wrap;font-size:14px}
.btns{display:grid;gap:4px;max-width:290px;margin-top:-2px}.btns button{background:#fff;border:0;border-radius:8px;padding:9px;color:#0F6E56;font-size:14px;cursor:pointer}
.btns button:hover{background:#f6f6f6}.img{width:100%;border-radius:8px;display:block;margin-bottom:6px}
.tpl{font-size:11px;color:#888780;margin-bottom:4px}.time{font-size:11px;color:#888780;text-align:center;margin:10px 0}
.bar{background:#F1EFE8;padding:8px;display:flex;gap:6px}.bar input{flex:1;border:0;border-radius:18px;padding:9px 12px;font-size:14px}
.bar button{border:0;background:#128C7E;color:#fff;border-radius:18px;padding:0 12px;cursor:pointer}
.panel{width:470px}.card{background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:14px;border:1px solid #e6e0d6}
.card h3{margin:0 0 8px;font-size:15px}textarea{width:100%;height:120px;font-family:monospace;font-size:12px;border:1px solid #ddd;border-radius:8px;padding:8px}
.card button{background:#fff;border:1px solid #bbb;border-radius:8px;padding:7px 10px;margin:3px 3px 3px 0;cursor:pointer}
.small{font-size:12px;color:#6b6a65}pre{white-space:pre;font-size:11px;margin:0;overflow-x:auto}
</style></head><body>
<div class="layout">
 <div class="phone">
  <div class="top"><div class="av">D101</div><div><div style="font-weight:600">Dinner 101</div><div style="font-size:11px;opacity:.8">Simulator</div></div></div>
  <div class="chat" id="chat"></div>
  <div class="bar"><input id="msg" placeholder="Type, or paste a voice-note transcript" onkeydown="if(event.key==='Enter')sendText()"><button onclick="sendText()">Send</button></div>
 </div>
 <div class="panel">
  <div class="card"><h3>Household</h3><input id="phone" value="sim-27820000001" style="width:100%;padding:6px"><div class="small">Each number is a separate household. Sim numbers never reach real WhatsApp.</div>
   <button onclick="resetUser()">Start this household over</button></div>
  <div class="card"><h3>Clock</h3><div id="clock" class="small"></div>
   <button onclick="clockTo('dinner')">Jump to dinner time</button><button onclick="clockTo('checkin')">+3 hours</button>
   <button onclick="clockTo('nextday')">Next day, 10:00</button><button onclick="clockTo('trial')">+13 days</button>
   <div class="small">Jumping runs the background jobs (dinner, check-in, reminders).</div></div>
  <div class="card"><h3>Send a till slip (as text)</h3>
   <textarea id="slip">PICK n PAY
PNP TOM LOOSE 1.2KG     24.99
PNP CHKN FLLT 1KG       89.99
CLOVER FRSH MLK 2L      36.99
2 x KOO BAKED BEANS     35.98
SASKO BRWN BRD          19.99
COLGATE TOOTHPASTE      29.99
TOTAL                  237.93</textarea><button onclick="sendSlip()">Send slip</button></div>
  <div class="card"><h3>Kitchen list (background view)</h3><pre id="pantry"></pre></div>
 </div>
</div>
<script>
const chat=document.getElementById('chat');
function phone(){return document.getElementById('phone').value.trim()}
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function fmt(s){return esc(s).replace(/\\*([^*]+)\\*/g,'<b>$1</b>')}
function addOut(t){const d=document.createElement('div');d.className='out';d.textContent=t;chat.appendChild(d)}
function addTime(t){const d=document.createElement('div');d.className='time';d.textContent=t;chat.appendChild(d)}
function render(msgs){for(const m of msgs){const d=document.createElement('div');d.className='in';let h='';
 if(m.via_template)h+='<div class="tpl">template: '+esc(m.via_template)+'</div>';
 if(m.image)h+='<img class="img" src="'+m.image+'">';else if(m.placeholder)h+='<img class="img" src="'+m.placeholder+'">';
 h+=fmt(m.body||'');d.innerHTML=h;chat.appendChild(d);
 if(m.buttons){const b=document.createElement('div');b.className='btns';for(const [id,title] of m.buttons){const x=document.createElement('button');x.textContent=title;x.onclick=()=>tap(id,title);b.appendChild(x)}chat.appendChild(b)}}
 chat.scrollTop=chat.scrollHeight;refresh()}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json()}
async function sendText(){const i=document.getElementById('msg');const t=i.value.trim();if(!t)return;i.value='';addOut('🎙️ '+t);render((await post('/sim/send',{phone:phone(),kind:'text',text:t})).messages)}
async function sendSlip(){addOut('📸 Till slip photo');render((await post('/sim/send',{phone:phone(),kind:'slip',text:document.getElementById('slip').value})).messages)}
async function tap(id,title){addOut(title);render((await post('/sim/send',{phone:phone(),kind:'button',button_id:id})).messages)}
async function clockTo(w){const r=await post('/sim/clock',{phone:phone(),to:w});addTime(r.now);render(r.messages)}
async function resetUser(){await post('/sim/reset',{phone:phone()});chat.innerHTML='';refresh()}
async function refresh(){const r=await (await fetch('/sim/state?phone='+encodeURIComponent(phone()))).json();document.getElementById('clock').textContent='Now: '+r.now+'  ·  dinner at '+(r.dinner_time||'-');document.getElementById('pantry').textContent=r.pantry}
refresh();
</script></body></html>"""


def plate_svg(name: str) -> str:
    n = html.escape(name)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 262 170"><rect width="262" height="170" fill="#BA7517"/>
<ellipse cx="131" cy="85" rx="96" ry="68" fill="#F1EFE8"/><ellipse cx="131" cy="85" rx="74" ry="52" fill="#fff"/>
<ellipse cx="131" cy="87" rx="58" ry="38" fill="#F0997B"/><circle cx="112" cy="78" r="9" fill="#FAEEDA"/><circle cx="148" cy="92" r="9" fill="#FAEEDA"/>
<circle cx="150" cy="70" r="5" fill="#E24B4A"/><ellipse cx="124" cy="100" rx="7" ry="4" fill="#3B6D11"/>
<rect x="0" y="146" width="262" height="24" fill="rgba(0,0,0,.45)"/><text x="131" y="162" font-family="sans-serif" font-size="12" fill="#fff" text-anchor="middle">Photo: {n}</text></svg>"""
