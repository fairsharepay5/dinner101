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


BRAND_CSS = """
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:#000;color:#fff;font-family:Poppins,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;line-height:1.55}
a{color:#FF6A01}
.w{max-width:1080px;margin:0 auto;padding:0 22px}
.nav{display:flex;justify-content:space-between;align-items:center;padding:18px 0}
.nav img{height:96px;width:auto}
.pill{display:inline-flex;align-items:center;gap:8px;background:#FF6A01;color:#000;font-weight:800;padding:14px 24px;border-radius:999px;text-decoration:none;font-size:17px;min-height:48px}
.pill:hover{background:#ff8a3a}
.ghost{color:#fff;text-decoration:none;font-weight:600;border:2px solid #333;border-radius:999px;padding:10px 18px;font-size:15px}
.hero{display:grid;grid-template-columns:1.1fr .9fr;gap:40px;align-items:center;padding:40px 0 70px}
.hero h1{font-size:clamp(40px,6vw,68px);line-height:1.02;margin:0 0 18px;font-weight:800;letter-spacing:-.02em}
.hero h1 span{color:#FF6A01}
.lead{font-size:19px;color:#d8d8d8;max-width:520px;margin:0 0 26px}
.small{color:#a9a9a9;font-size:14px;margin-top:14px}
.script{font-family:'Kaushan Script',cursive;font-size:clamp(30px,4vw,44px);color:#fff;margin:0}
.uline{height:5px;width:220px;background:#FF6A01;border-radius:4px;margin:6px 0 0;transform:rotate(-1.5deg)}
.phone{background:#0d0d0d;border:1px solid #262626;border-radius:28px;padding:18px;max-width:380px;justify-self:center;width:100%}
.chat{background:#1b1b1b;border-radius:18px;padding:16px}
.time{text-align:center;color:#9a9a9a;font-size:13px;margin-bottom:10px}
.bubble{background:#fff;color:#111;border-radius:4px 16px 16px 16px;padding:14px 16px}
.bubble b{display:block;font-size:17px;margin-bottom:4px}
.bubble p{margin:0;font-size:14px;color:#333}
.btns{display:grid;gap:6px;margin-top:6px}
.btns span{background:#fff;color:#0F6E56;border-radius:12px;text-align:center;padding:10px;font-weight:600;font-size:14px}
.brush{background:#FF6A01;color:#000;font-weight:800;text-transform:uppercase;font-size:clamp(26px,4.4vw,46px);text-align:center;padding:18px 20px;margin:0 0 60px;transform:rotate(-1.2deg);clip-path:polygon(1% 12%,99% 0,100% 88%,0 100%)}
.feats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;margin:0 0 70px}
.feat{text-align:center;padding:10px 22px;border-left:2px solid #FF6A01}
.feat:first-child{border-left:0}
.feat svg{width:64px;height:64px;stroke:#fff;fill:none;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
.feat h3{font-size:18px;text-transform:uppercase;margin:12px 0 6px;font-weight:800;letter-spacing:.02em}
.feat p{margin:0;color:#bdbdbd;font-size:15px}
h2{font-size:clamp(30px,4vw,42px);font-weight:800;margin:0 0 26px;letter-spacing:-.01em}
h2 span{color:#FF6A01}
.steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:70px}
.step{background:#0f0f0f;border:1px solid #232323;border-radius:20px;padding:22px}
.num{width:44px;height:44px;border-radius:22px;background:#FF6A01;color:#000;font-weight:800;display:flex;align-items:center;justify-content:center;margin-bottom:12px;font-size:20px}
.step h3{margin:0 0 6px;font-size:18px}.step p{margin:0;color:#bdbdbd;font-size:15px}
.braai{display:grid;grid-template-columns:1fr 1fr;gap:30px;align-items:center;background:#111;border-radius:28px;padding:36px;margin-bottom:70px;border:1px solid #232323}
.braai ul{margin:0;padding-left:20px;color:#d8d8d8}.braai li{margin:4px 0}
.list{background:#fff;color:#111;border-radius:16px;padding:18px 20px;font-size:15px}
.list b{display:block;margin-bottom:6px}
.price{text-align:center;padding:50px 22px;border-top:1px solid #222}
.price .big{font-size:clamp(44px,7vw,72px);font-weight:800;margin:0}
.price .big span{color:#FF6A01}
.qr{background:#fff;border-radius:16px;padding:12px;width:180px;margin:26px auto 8px}
footer{border-top:1px solid #222;padding:26px 0 40px;color:#9a9a9a;font-size:14px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px}
footer a{color:#d8d8d8;text-decoration:none;margin-right:16px}
@media (max-width:820px){.hero{grid-template-columns:1fr;padding-top:16px}.steps{grid-template-columns:1fr 1fr}.braai{grid-template-columns:1fr;padding:24px}}
@media (max-width:560px){.feats{grid-template-columns:1fr;gap:26px}.feat{border-left:0;border-top:2px solid #FF6A01;padding-top:22px}.feat:first-child{border-top:0}.steps{grid-template-columns:1fr}.nav .ghost{display:none}}
"""

ICON_PANTRY = '<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="10" y="8" width="44" height="48" rx="3"/><path d="M10 32h44"/><rect x="16" y="16" width="8" height="12" rx="2"/><rect x="28" y="19" width="8" height="9" rx="2"/><rect x="40" y="14" width="8" height="14" rx="2"/><rect x="16" y="40" width="10" height="10" rx="2"/><rect x="31" y="38" width="7" height="12" rx="2"/><rect x="42" y="42" width="7" height="8" rx="2"/></svg>'
ICON_CAL = '<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="8" y="12" width="40" height="38" rx="4"/><path d="M8 22h40M18 6v10M38 6v10"/><circle cx="45" cy="46" r="11"/><path d="M45 40v6l4 3"/></svg>'
ICON_CLOCHE = '<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M8 46h48M12 46a20 20 0 0 1 40 0"/><circle cx="32" cy="23" r="3"/><path d="M26 8c-2 3 2 4 0 7M32 6c-2 3 2 4 0 7M38 8c-2 3 2 4 0 7"/><path d="M6 52h52"/></svg>'


def landing() -> str:
    link = wa_link()
    days = settings.trial_days
    price = f"R{settings.price_rands:.0f}"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dinner 101 · Smart meals. Less waste.</title>
<meta name="description" content="One dinner idea a day on WhatsApp, made from what's already in your kitchen. Try it free for {days} days.">
<meta property="og:title" content="Dinner 101 · Smart meals. Less waste."><meta property="og:image" content="/brand/logo.png">
<link rel="icon" href="/brand/logo.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Kaushan+Script&family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
<style>{BRAND_CSS}</style></head><body>
<div class="w">
<nav class="nav"><a href="/" aria-label="Dinner 101 home"><img src="/brand/logo.png" alt="Dinner 101"></a><a class="ghost" href="{link}">Start on WhatsApp</a></nav>

<section class="hero">
<div>
<h1>What's for dinner?<br><span>It's already in your kitchen.</span></h1>
<p class="lead">Every afternoon Dinner 101 sends you <b>one dinner idea</b> on WhatsApp, made from what you already have, and it uses up food before it goes off.</p>
<a class="pill" href="{link}">Say Hi on WhatsApp</a>
<p class="small">{days} days free, then {price}/month. No app to download. Cancel any time.</p>
<p class="script" style="margin-top:28px">Smart Meals. Less Waste.</p><div class="uline"></div>
</div>
<div class="phone" aria-label="Example WhatsApp message from Dinner 101"><div class="chat">
<div class="time">Today 16:30</div>
<div class="bubble"><b>Tonight: Chicken &amp; mushroom pasta</b><p>30 min · serves 4. Uses up your mushrooms and cheese before they go off. Everything's at home.</p></div>
<div class="btns"><span>Let's cook it</span><span>Something else</span><span>Show recipe</span></div>
</div></div>
</section>

<div class="brush">No more "what's for dinner?" stress</div>

<section class="feats">
<div class="feat">{ICON_PANTRY}<h3>Track your kitchen</h3><p>A voice note or a photo of your till slip. We keep the list.</p></div>
<div class="feat">{ICON_CAL}<h3>Get dinner ideas</h3><p>One idea every afternoon, at the time that suits you.</p></div>
<div class="feat">{ICON_CLOCHE}<h3>Cook with confidence</h3><p>Step-by-step recipe, and your list updates when you've cooked.</p></div>
</section>

<section>
<h2>How it <span>works</span></h2>
<div class="steps">
<div class="step"><div class="num">1</div><h3>Say Hi</h3><p>Message Dinner 101 on WhatsApp. That's the whole sign-up.</p></div>
<div class="step"><div class="num">2</div><h3>Talk your kitchen</h3><p>Walk around and send a voice note of what you have. English or Afrikaans.</p></div>
<div class="step"><div class="num">3</div><h3>Dinner at 16:30</h3><p>Get tonight's idea with buttons: cook it, something else, or the recipe.</p></div>
<div class="step"><div class="num">4</div><h3>Tap "Cooked it"</h3><p>Your kitchen list updates itself. Snap your slip when you shop.</p></div>
</div>
</section>

<section class="braai">
<div>
<h2 style="margin-bottom:14px">Braai for 6? <span>Just ask.</span></h2>
<ul><li>"What's in my freezer?" and you get the list.</li>
<li>"We're braaiing for 6 tonight, what do I need?" and you get what's at home plus a ready shopping list.</li>
<li>"Send my dinner idea at six" and it's done.</li></ul>
</div>
<div class="list"><b>🛒 Shopping list: Braai for 6</b>Rump steak, 1.5 kg<br>White bread, 2 loaves<br>Tomatoes, 4<br>Cheddar, 400 g<br><span style="color:#666">Already at home: onions, butter, chutney</span></div>
</section>
</div>

<section class="price">
<p class="big">{days} days <span>free</span></p>
<p style="color:#d8d8d8;font-size:18px;margin:6px 0 24px">Then {price} a month. Cancel any time by sending "cancel".</p>
<a class="pill" href="{link}">Start on WhatsApp</a>
<div class="qr">{qr_svg(link)}</div>
<p class="small">Scan with your phone camera to open WhatsApp</p>
</section>

<div class="w"><footer>
<div><a href="https://www.instagram.com/getdinner101/">Instagram @getdinner101</a><a href="/privacy">Privacy</a><a href="/terms">Terms</a></div>
<div>© Dinner 101 · Pips to Profit (Pty) Ltd</div>
</footer></div>
</body></html>"""


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
