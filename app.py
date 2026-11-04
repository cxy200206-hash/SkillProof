import os, sqlite3, secrets, hashlib, hmac, html, urllib.parse, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('SKILLPROOF_DB', os.path.join(BASE_DIR, 'skillproof.db'))
PORT = int(os.environ.get('PORT', '8000'))


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 160_000)
    return salt.hex() + '$' + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split('$', 1)
        test = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt_hex), 160_000).hex()
        return hmac.compare_digest(test, digest_hex)
    except Exception:
        return False


def init_db():
    conn = db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('student','business')),
      headline TEXT DEFAULT '',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
      token TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS projects (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      business_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      category TEXT NOT NULL,
      description TEXT NOT NULL,
      deliverables TEXT NOT NULL,
      skills TEXT NOT NULL,
      budget INTEGER NOT NULL,
      weeks INTEGER NOT NULL,
      remote INTEGER NOT NULL DEFAULT 1,
      status TEXT NOT NULL DEFAULT 'open',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS applications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      note TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'applied' CHECK(status IN ('applied','accepted','rejected','submitted','verified')),
      submission_url TEXT DEFAULT '',
      submission_notes TEXT DEFAULT '',
      employer_feedback TEXT DEFAULT '',
      rating INTEGER,
      verified_at TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(project_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT DEFAULT '',
      email TEXT DEFAULT '',
      role TEXT DEFAULT '',
      score INTEGER,
      message TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    ''')
    # Seed demo users and projects once
    n = conn.execute('SELECT COUNT(*) AS c FROM users').fetchone()['c']
    if n == 0:
        conn.execute('INSERT INTO users(name,email,password_hash,role,headline,created_at) VALUES(?,?,?,?,?,?)',
                     ('Maya Student','student@skillproof.demo',hash_password('demo123'),'student','Business student building verified experience',now_iso()))
        conn.execute('INSERT INTO users(name,email,password_hash,role,headline,created_at) VALUES(?,?,?,?,?,?)',
                     ('Alex Chen','business@skillproof.demo',hash_password('demo123'),'business','Founder, Northstar Studio',now_iso()))
        conn.execute('INSERT INTO users(name,email,password_hash,role,headline,created_at) VALUES(?,?,?,?,?,?)',
                     ('Priya Rao','cafe@skillproof.demo',hash_password('demo123'),'business','Owner, Kindred Café',now_iso()))
        b1 = conn.execute("SELECT id FROM users WHERE email='business@skillproof.demo'").fetchone()['id']
        b2 = conn.execute("SELECT id FROM users WHERE email='cafe@skillproof.demo'").fetchone()['id']
        seed = [
          (b2,'Social Media Content Plan','Marketing','Create a practical 7-day content plan for a local café.','7-post content calendar; 3 sample captions; 1 simple performance checklist','Content planning, copywriting, research',250,2,1),
          (b1,'Competitor Research Sprint','Business Research','Research 5 competitors and summarise positioning, pricing and differentiators.','Competitor matrix; 2-page insight summary; 5-slide recommendation deck','Research, analysis, presentation',320,2,1),
          (b1,'Landing Page UX Review','Design','Review a small-business landing page and propose evidence-based UX improvements.','Annotated review; prioritised recommendations; simple wireframe','UX, communication, design thinking',400,3,1),
          (b2,'Customer Survey Analysis','Data','Analyse a small anonymised customer survey and turn it into clear business insights.','Cleaned spreadsheet; 4 charts; 1-page insight memo','Excel, data analysis, business communication',300,2,1)
        ]
        conn.executemany('''INSERT INTO projects(business_id,title,category,description,deliverables,skills,budget,weeks,remote,status,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?,'open',?)''', [x + (now_iso(),) for x in seed])
    conn.commit(); conn.close()


def e(v): return html.escape(str(v or ''))


def page(title, body, user=None, notice=''):
    role_badge = ''
    auth = '<a class="btn ghost" href="/login">Log in</a><a class="btn" href="/register">Create account</a>'
    if user:
        role_badge = f'<span class="role">{e(user["role"]).title()}</span>'
        auth = f'<a href="/dashboard">Dashboard</a><a href="/portfolio">Portfolio</a><form class="inline" method="post" action="/logout"><button class="linkbtn">Log out</button></form>'
    note_html = f'<div class="notice">{e(notice)}</div>' if notice else ''
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{e(title)} · SkillProof</title><link rel="stylesheet" href="/static/style.css"></head><body>
    <header><a class="brand" href="/"><span class="mark">S</span><b>Skill<span>Proof</span></b></a><nav>{role_badge}<a href="/projects">Projects</a><a href="/feedback">Feedback</a>{auth}</nav></header>
    {note_html}<main>{body}</main><footer><div><b>SkillProof</b> · Real Projects. Real Experience. Real Proof.</div><small>Concept venture prototype. Demo projects, users and budgets are illustrative.</small></footer></body></html>'''


class App(BaseHTTPRequestHandler):
    server_version = 'SkillProof/1.0'

    def log_message(self, fmt, *args):
        print('[SkillProof]', fmt % args)

    def send_html(self, content, status=200, headers=None):
        data = content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        if headers:
            for k,v in headers: self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)

    def redirect(self, path, cookie=None):
        headers=[('Location',path)]
        if cookie: headers.append(('Set-Cookie',cookie))
        self.send_response(303)
        for k,v in headers: self.send_header(k,v)
        self.end_headers()

    def parse_body(self):
        length=int(self.headers.get('Content-Length','0') or 0)
        raw=self.rfile.read(length).decode('utf-8')
        return {k:v[-1] for k,v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def query(self):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

    def path_only(self): return urllib.parse.urlsplit(self.path).path

    def current_user(self):
        c=SimpleCookie(self.headers.get('Cookie',''))
        token=c.get('sp_session')
        if not token: return None
        conn=db()
        row=conn.execute('''SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?''',(token.value, now_iso())).fetchone()
        conn.close(); return row

    def require(self, role=None):
        u=self.current_user()
        if not u:
            self.redirect('/login?next='+urllib.parse.quote(self.path)); return None
        if role and u['role']!=role:
            self.send_html(page('Not allowed','<section class="card"><h1>Not allowed</h1><p>This page is for '+e(role)+' accounts.</p></section>',u),403); return None
        return u

    def do_GET(self):
        path=self.path_only(); u=self.current_user()
        if path.startswith('/static/'):
            fp=os.path.join(BASE_DIR,path.lstrip('/'))
            if os.path.isfile(fp):
                data=open(fp,'rb').read(); self.send_response(200); self.send_header('Content-Type','text/css'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
            self.send_error(404); return
        if path=='/': return self.home(u)
        if path=='/register': return self.register_form(u)
        if path=='/login': return self.login_form(u)
        if path=='/projects': return self.projects(u)
        if path=='/project': return self.project_detail(u)
        if path=='/dashboard': return self.dashboard()
        if path=='/business/new': return self.new_project_form()
        if path=='/workspace': return self.workspace()
        if path=='/portfolio': return self.portfolio()
        if path=='/feedback': return self.feedback_form(u)
        if path=='/demo-login': return self.demo_login()
        self.send_html(page('Not found','<section class="card"><h1>Page not found</h1></section>',u),404)

    def do_POST(self):
        path=self.path_only()
        if path=='/register': return self.register()
        if path=='/login': return self.login()
        if path=='/logout': return self.logout()
        if path=='/apply': return self.apply()
        if path=='/business/new': return self.create_project()
        if path=='/business/application-status': return self.application_status()
        if path=='/submit-work': return self.submit_work()
        if path=='/business/review': return self.review()
        if path=='/feedback': return self.save_feedback()
        self.send_error(404)

    def home(self,u):
        body='''<section class="hero"><div><div class="eyebrow">EARLY-CAREER PROJECT PLATFORM</div><h1>Turn your skills into <span>proof.</span></h1><p class="lead">SkillProof connects emerging talent with short, clearly-scoped projects from real businesses—so students can gain experience, receive project-based payment, get employer feedback and build verified evidence.</p><div class="actions"><a class="btn big" href="/projects">Explore projects</a><a class="btn ghost big" href="/demo-login?role=student">Try student demo</a><a class="btn ghost big" href="/demo-login?role=business">Try business demo</a></div></div><div class="hero-card"><div class="mini">LIVE WORKFLOW</div><h3>Find → Work → Verify</h3><div class="journey"><b>01</b><span>Find a scoped project</span><b>02</b><span>Complete real work</span><b>03</b><span>Receive verified feedback</span></div></div></section>
        <section class="three"><div class="card"><h3>Real experience</h3><p>Apply university skills to genuine business needs with clear deliverables.</p></div><div class="card"><h3>Fair project model</h3><p>Each project shows an agreed budget, timeline and expected output before application.</p></div><div class="card"><h3>Verified proof</h3><p>Employer review becomes evidence that can be shown in a SkillProof portfolio.</p></div></section>
        <section class="split"><div><div class="eyebrow">WHY NOT JUST AN INTERNSHIP?</div><h2>Project capability is different from workplace capability.</h2><p>SkillProof is designed for finite, beginner-appropriate projects. Internships remain valuable for longer-term team integration, supervision and workplace immersion.</p></div><div class="path"><span>Coursework</span><i>→</i><strong>SkillProof</strong><i>→</i><span>Internship</span><i>→</i><span>Graduate role</span></div></section>'''
        self.send_html(page('Home',body,u))

    def register_form(self,u):
        if u: return self.redirect('/dashboard')
        body='''<section class="auth card"><h1>Create account</h1><p>Choose the side of the SkillProof marketplace you want to test.</p><form method="post" action="/register"><label>Name<input name="name" required></label><label>Email<input name="email" type="email" required></label><label>Password<input name="password" type="password" minlength="6" required></label><label>Role<select name="role"><option value="student">Student</option><option value="business">Business</option></select></label><button class="btn big">Create account</button></form></section>'''
        self.send_html(page('Register',body,u))

    def register(self):
        d=self.parse_body(); name=d.get('name','').strip(); email=d.get('email','').strip().lower(); pw=d.get('password',''); role=d.get('role','student')
        if not name or '@' not in email or len(pw)<6 or role not in ('student','business'):
            return self.send_html(page('Register','<section class="card"><h1>Check your details</h1><p>Please provide a valid name, email, password and role.</p><a href="/register">Go back</a></section>'),400)
        conn=db()
        try:
            cur=conn.execute('INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)',(name,email,hash_password(pw),role,now_iso())); conn.commit(); uid=cur.lastrowid
        except sqlite3.IntegrityError:
            conn.close(); return self.send_html(page('Register','<section class="card"><h1>Email already exists</h1><a href="/login">Log in instead</a></section>'),400)
        conn.close(); return self.create_session(uid,'/dashboard')

    def login_form(self,u):
        if u: return self.redirect('/dashboard')
        body='''<section class="auth card"><h1>Log in</h1><form method="post" action="/login"><label>Email<input name="email" type="email" required></label><label>Password<input name="password" type="password" required></label><button class="btn big">Log in</button></form><div class="demo"><b>Demo accounts</b><code>student@skillproof.demo / demo123</code><code>business@skillproof.demo / demo123</code></div></section>'''
        self.send_html(page('Login',body,u))

    def login(self):
        d=self.parse_body(); email=d.get('email','').strip().lower(); pw=d.get('password','')
        conn=db(); row=conn.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); conn.close()
        if not row or not verify_password(pw,row['password_hash']):
            return self.send_html(page('Login','<section class="auth card"><h1>Login failed</h1><p>Email or password was incorrect.</p><a href="/login">Try again</a></section>'),401)
        return self.create_session(row['id'],'/dashboard')

    def create_session(self,uid,dest):
        token=secrets.token_urlsafe(32); expires=(datetime.datetime.utcnow()+datetime.timedelta(days=7)).replace(microsecond=0).isoformat()+'Z'
        conn=db(); conn.execute('INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)',(token,uid,expires)); conn.commit(); conn.close()
        cookie=f'sp_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800'
        self.redirect(dest,cookie)

    def logout(self):
        c=SimpleCookie(self.headers.get('Cookie','')); tok=c.get('sp_session')
        if tok:
            conn=db(); conn.execute('DELETE FROM sessions WHERE token=?',(tok.value,)); conn.commit(); conn.close()
        self.redirect('/', 'sp_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0')

    def demo_login(self):
        role=(self.query().get('role') or ['student'])[0]
        email='student@skillproof.demo' if role=='student' else 'business@skillproof.demo'
        conn=db(); row=conn.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone(); conn.close(); self.create_session(row['id'],'/dashboard')

    def projects(self,u):
        q=self.query(); category=(q.get('category') or [''])[0]; search=(q.get('q') or [''])[0].strip()
        sql='''SELECT p.*,u.name business_name FROM projects p JOIN users u ON u.id=p.business_id WHERE p.status='open' '''; args=[]
        if category: sql+=' AND p.category=?'; args.append(category)
        if search: sql+=' AND (p.title LIKE ? OR p.description LIKE ? OR p.skills LIKE ?)'; args += ['%'+search+'%']*3
        sql+=' ORDER BY p.id DESC'
        conn=db(); rows=conn.execute(sql,args).fetchall(); cats=[r['category'] for r in conn.execute("SELECT DISTINCT category FROM projects WHERE status='open' ORDER BY category")]; conn.close()
        filters=''.join(f'<a class="chip" href="/projects?category={urllib.parse.quote(c)}">{e(c)}</a>' for c in cats)
        cards=''.join(f'''<article class="project card"><div class="project-top"><span class="tag">{e(r['category'])}</span><b>A${r['budget']}</b></div><h3>{e(r['title'])}</h3><p>{e(r['description'])}</p><div class="meta"><span>{r['weeks']} weeks</span><span>{'Remote' if r['remote'] else 'On-site'}</span><span>{e(r['business_name'])}</span></div><a class="btn" href="/project?id={r['id']}">View brief</a></article>''' for r in rows) or '<div class="card"><p>No matching projects yet.</p></div>'
        body=f'''<section><div class="eyebrow">PROJECT MARKETPLACE</div><h1>Find a real project</h1><form class="search" method="get"><input name="q" value="{e(search)}" placeholder="Search skills, projects or industries"><button class="btn">Search</button></form><div class="chips"><a class="chip" href="/projects">All</a>{filters}</div><div class="grid">{cards}</div></section>'''
        self.send_html(page('Projects',body,u))

    def project_detail(self,u):
        try: pid=int((self.query().get('id') or ['0'])[0])
        except: pid=0
        conn=db(); r=conn.execute('''SELECT p.*,u.name business_name,u.headline business_headline FROM projects p JOIN users u ON u.id=p.business_id WHERE p.id=?''',(pid,)).fetchone(); app=None
        if u and u['role']=='student': app=conn.execute('SELECT * FROM applications WHERE project_id=? AND student_id=?',(pid,u['id'])).fetchone()
        conn.close()
        if not r: return self.send_html(page('Project','<section class="card"><h1>Project not found</h1></section>',u),404)
        if u and u['role']=='student':
            if app: cta=f'<div class="status">Application status: <b>{e(app["status"]).title()}</b></div>'
            else: cta=f'''<form class="apply card" method="post" action="/apply"><input type="hidden" name="project_id" value="{r['id']}"><label>Why are you a fit?<textarea name="note" placeholder="Briefly connect your skills to the project"></textarea></label><button class="btn big">Apply for this project</button></form>'''
        elif u and u['role']=='business': cta='<div class="status">Business accounts can publish and manage projects from the dashboard.</div>'
        else: cta='<a class="btn big" href="/login">Log in to apply</a>'
        body=f'''<section class="brief"><div><div class="eyebrow">{e(r['category']).upper()}</div><h1>{e(r['title'])}</h1><p class="lead">{e(r['description'])}</p><div class="brief-grid"><div><small>Project budget</small><strong>A${r['budget']}</strong></div><div><small>Duration</small><strong>{r['weeks']} weeks</strong></div><div><small>Location</small><strong>{'Remote' if r['remote'] else 'On-site'}</strong></div></div><div class="card"><h3>Deliverables</h3><p>{e(r['deliverables'])}</p><h3>Skills</h3><p>{e(r['skills'])}</p></div>{cta}</div><aside class="card company"><small>PROJECT FROM</small><h3>{e(r['business_name'])}</h3><p>{e(r['business_headline'])}</p><hr><p>SkillProof projects are designed around defined outputs, timelines and budgets.</p></aside></section>'''
        self.send_html(page(r['title'],body,u))

    def apply(self):
        u=self.require('student')
        if not u: return
        d=self.parse_body(); pid=int(d.get('project_id','0') or 0); note=d.get('note','').strip()
        conn=db()
        try: conn.execute('INSERT INTO applications(project_id,student_id,note,status,created_at) VALUES(?,?,?,\'applied\',?)',(pid,u['id'],note,now_iso())); conn.commit()
        except sqlite3.IntegrityError: pass
        conn.close(); self.redirect('/dashboard')

    def dashboard(self):
        u=self.require()
        if not u: return
        conn=db()
        if u['role']=='student':
            rows=conn.execute('''SELECT a.*,p.title,p.category,p.budget,u.name business_name FROM applications a JOIN projects p ON p.id=a.project_id JOIN users u ON u.id=p.business_id WHERE a.student_id=? ORDER BY a.id DESC''',(u['id'],)).fetchall()
            items=''.join(f'''<tr><td><b>{e(r['title'])}</b><br><small>{e(r['business_name'])}</small></td><td>A${r['budget']}</td><td><span class="pill {e(r['status'])}">{e(r['status']).title()}</span></td><td>{('<a href="/workspace?application_id='+str(r['id'])+'">Open workspace</a>') if r['status'] in ('accepted','submitted','verified') else '—'}</td></tr>''' for r in rows) or '<tr><td colspan="4">No applications yet. <a href="/projects">Browse projects</a>.</td></tr>'
            body=f'''<section><div class="eyebrow">STUDENT DASHBOARD</div><h1>Welcome, {e(u['name'])}</h1><div class="stats"><div class="card"><b>{len(rows)}</b><span>Applications</span></div><div class="card"><b>{sum(1 for r in rows if r['status']=='verified')}</b><span>Verified projects</span></div><div class="card"><b>A${sum(r['budget'] for r in rows if r['status']=='verified')}</b><span>Verified project value</span></div></div><div class="card tablewrap"><h2>Your project journey</h2><table><thead><tr><th>Project</th><th>Budget</th><th>Status</th><th>Workspace</th></tr></thead><tbody>{items}</tbody></table></div></section>'''
        else:
            projs=conn.execute('SELECT * FROM projects WHERE business_id=? ORDER BY id DESC',(u['id'],)).fetchall()
            apps=conn.execute('''SELECT a.*,p.title,st.name student_name,st.email student_email FROM applications a JOIN projects p ON p.id=a.project_id JOIN users st ON st.id=a.student_id WHERE p.business_id=? ORDER BY a.id DESC''',(u['id'],)).fetchall()
            cards=''.join(f'<div class="card"><b>{e(p["title"])}</b><div class="meta"><span>A${p["budget"]}</span><span>{p["weeks"]} weeks</span><span>{e(p["status"])}</span></div></div>' for p in projs) or '<div class="card">No projects yet.</div>'
            ar=''.join(f'''<tr><td>{e(a['student_name'])}<br><small>{e(a['student_email'])}</small></td><td>{e(a['title'])}</td><td><span class="pill {e(a['status'])}">{e(a['status']).title()}</span></td><td><a href="/workspace?application_id={a['id']}">Review</a></td></tr>''' for a in apps) or '<tr><td colspan="4">No applications yet.</td></tr>'
            body=f'''<section><div class="eyebrow">BUSINESS DASHBOARD</div><div class="title-row"><div><h1>Welcome, {e(u['name'])}</h1><p>Publish scoped work, select emerging talent and verify completed outcomes.</p></div><a class="btn big" href="/business/new">+ Create project</a></div><h2>Your projects</h2><div class="grid smallgrid">{cards}</div><div class="card tablewrap"><h2>Applications & delivery</h2><table><thead><tr><th>Student</th><th>Project</th><th>Status</th><th>Action</th></tr></thead><tbody>{ar}</tbody></table></div></section>'''
        conn.close(); self.send_html(page('Dashboard',body,u))

    def new_project_form(self):
        u=self.require('business')
        if not u: return
        body='''<section class="formpage"><div class="eyebrow">BUSINESS PROJECT BUILDER</div><h1>Create a scoped project</h1><p class="lead">Define the output before a student applies. This is what keeps SkillProof different from vague unpaid “experience”.</p><form class="card" method="post" action="/business/new"><label>Project title<input name="title" required placeholder="e.g. Competitor Research Sprint"></label><label>Category<select name="category"><option>Business Research</option><option>Marketing</option><option>Design</option><option>Data</option><option>Technology</option></select></label><label>Project description<textarea name="description" required></textarea></label><label>Deliverables<textarea name="deliverables" required placeholder="List exactly what the student will hand over"></textarea></label><label>Skills<input name="skills" required placeholder="Research, Excel, copywriting"></label><div class="two"><label>Budget (AUD)<input name="budget" type="number" min="50" required></label><label>Duration (weeks)<input name="weeks" type="number" min="1" max="12" required></label></div><label class="check"><input type="checkbox" name="remote" value="1" checked> Remote-friendly</label><button class="btn big">Publish project</button></form></section>'''
        self.send_html(page('Create project',body,u))

    def create_project(self):
        u=self.require('business')
        if not u: return
        d=self.parse_body()
        try: budget=max(50,int(d.get('budget','0'))); weeks=max(1,min(12,int(d.get('weeks','1'))))
        except: return self.send_error(400)
        vals=(u['id'],d.get('title','').strip(),d.get('category','Business Research'),d.get('description','').strip(),d.get('deliverables','').strip(),d.get('skills','').strip(),budget,weeks,1 if d.get('remote')=='1' else 0,now_iso())
        if not all(vals[1:6]): return self.send_error(400)
        conn=db(); conn.execute('''INSERT INTO projects(business_id,title,category,description,deliverables,skills,budget,weeks,remote,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,'open',?)''',vals); conn.commit(); conn.close(); self.redirect('/dashboard')

    def workspace(self):
        u=self.require()
        if not u: return
        try: aid=int((self.query().get('application_id') or ['0'])[0])
        except: aid=0
        conn=db(); a=conn.execute('''SELECT a.*,p.*,st.name student_name,st.email student_email,b.name business_name FROM applications a JOIN projects p ON p.id=a.project_id JOIN users st ON st.id=a.student_id JOIN users b ON b.id=p.business_id WHERE a.id=?''',(aid,)).fetchone(); conn.close()
        if not a or not (u['id']==a['student_id'] or u['id']==a['business_id']): return self.send_html(page('Workspace','<section class="card"><h1>Workspace unavailable</h1></section>',u),403)
        timeline=f'''<div class="timeline"><span class="done">Applied</span><span class="{'done' if a['status'] in ('accepted','submitted','verified') else ''}">Accepted</span><span class="{'done' if a['status'] in ('submitted','verified') else ''}">Submitted</span><span class="{'done' if a['status']=='verified' else ''}">Verified</span></div>'''
        actions=''
        if u['role']=='business' and a['status']=='applied':
            actions=f'''<form class="inline-actions" method="post" action="/business/application-status"><input type="hidden" name="application_id" value="{aid}"><button class="btn" name="status" value="accepted">Accept student</button><button class="btn danger" name="status" value="rejected">Reject</button></form>'''
        elif u['role']=='student' and a['status']=='accepted':
            actions=f'''<form class="card" method="post" action="/submit-work"><h3>Submit final work</h3><input type="hidden" name="application_id" value="{aid}"><label>Portfolio / file link<input name="submission_url" type="url" required placeholder="https://..."></label><label>Submission notes<textarea name="submission_notes" required placeholder="What did you deliver and what changed?"></textarea></label><button class="btn big">Submit to business</button></form>'''
        elif u['role']=='business' and a['status']=='submitted':
            actions=f'''<form class="card" method="post" action="/business/review"><h3>Verify completed work</h3><input type="hidden" name="application_id" value="{aid}"><label>Employer feedback<textarea name="employer_feedback" required placeholder="Describe what the student completed and how well they performed"></textarea></label><label>Rating<select name="rating"><option value="5">5 — Excellent</option><option value="4">4 — Strong</option><option value="3">3 — Good</option><option value="2">2 — Needs improvement</option><option value="1">1 — Poor</option></select></label><button class="btn big">Verify project</button></form>'''
        elif a['status']=='verified':
            actions=f'''<div class="verified card"><div class="seal">✓</div><div><h3>Verified experience</h3><p>{e(a['employer_feedback'])}</p><b>{'★'*int(a['rating'] or 0)}</b></div></div>'''
        else: actions=f'<div class="status">Current status: <b>{e(a["status"]).title()}</b></div>'
        submit=''
        if a['submission_url']:
            safeurl=e(a['submission_url']); submit=f'<div class="card"><h3>Submitted work</h3><p><a href="{safeurl}" target="_blank" rel="noopener">{safeurl}</a></p><p>{e(a["submission_notes"])}</p></div>'
        body=f'''<section><div class="eyebrow">PROJECT WORKSPACE</div><h1>{e(a['title'])}</h1>{timeline}<div class="two-col"><div><div class="card"><small>STUDENT</small><h3>{e(a['student_name'])}</h3><small>BUSINESS</small><h3>{e(a['business_name'])}</h3><hr><b>Deliverables</b><p>{e(a['deliverables'])}</p><b>Agreed project budget</b><p>A${a['budget']}</p></div>{submit}</div><div>{actions}</div></div></section>'''
        self.send_html(page('Project workspace',body,u))

    def application_status(self):
        u=self.require('business')
        if not u:return
        d=self.parse_body(); aid=int(d.get('application_id','0')); status=d.get('status','')
        if status not in ('accepted','rejected'): return self.send_error(400)
        conn=db(); conn.execute('''UPDATE applications SET status=? WHERE id=? AND project_id IN (SELECT id FROM projects WHERE business_id=?) AND status='applied' ''',(status,aid,u['id'])); conn.commit(); conn.close(); self.redirect('/dashboard')

    def submit_work(self):
        u=self.require('student')
        if not u:return
        d=self.parse_body(); aid=int(d.get('application_id','0')); url=d.get('submission_url','').strip(); notes=d.get('submission_notes','').strip()
        if not (url.startswith('http://') or url.startswith('https://')) or not notes: return self.send_error(400)
        conn=db(); conn.execute("UPDATE applications SET submission_url=?,submission_notes=?,status='submitted' WHERE id=? AND student_id=? AND status='accepted'",(url,notes,aid,u['id'])); conn.commit(); conn.close(); self.redirect('/workspace?application_id='+str(aid))

    def review(self):
        u=self.require('business')
        if not u:return
        d=self.parse_body(); aid=int(d.get('application_id','0')); fb=d.get('employer_feedback','').strip(); rating=max(1,min(5,int(d.get('rating','5'))))
        if not fb:return self.send_error(400)
        conn=db(); conn.execute('''UPDATE applications SET employer_feedback=?,rating=?,status='verified',verified_at=? WHERE id=? AND status='submitted' AND project_id IN (SELECT id FROM projects WHERE business_id=?)''',(fb,rating,now_iso(),aid,u['id'])); conn.commit(); conn.close(); self.redirect('/workspace?application_id='+str(aid))

    def portfolio(self):
        u=self.require('student')
        if not u:return
        conn=db(); rows=conn.execute('''SELECT a.*,p.title,p.category,p.skills,p.budget,b.name business_name FROM applications a JOIN projects p ON p.id=a.project_id JOIN users b ON b.id=p.business_id WHERE a.student_id=? AND a.status='verified' ORDER BY a.verified_at DESC''',(u['id'],)).fetchall(); conn.close()
        cards=''.join(f'''<article class="card proof"><div class="proof-head"><span class="seal small">✓</span><div><small>VERIFIED PROJECT</small><h3>{e(r['title'])}</h3></div></div><p><b>{e(r['business_name'])}</b> · {e(r['category'])}</p><p>{e(r['employer_feedback'])}</p><div class="meta"><span>{'★'*int(r['rating'] or 0)}</span><span>A${r['budget']} project value</span></div><div class="skills">{''.join('<span>'+e(s.strip())+'</span>' for s in r['skills'].split(','))}</div></article>''' for r in rows) or '<div class="card"><h3>No verified work yet</h3><p>Complete a project and receive employer verification to build your portfolio.</p><a href="/projects">Explore projects</a></div>'
        body=f'''<section><div class="eyebrow">VERIFIED PORTFOLIO</div><h1>{e(u['name'])}</h1><p class="lead">A record of work verified by participating businesses.</p><div class="grid">{cards}</div></section>'''; self.send_html(page('Portfolio',body,u))

    def feedback_form(self,u):
        body='''<section class="formpage"><div class="eyebrow">VENTURE FEEDBACK</div><h1>Help us improve SkillProof</h1><p class="lead">This form is intentionally separate from the product workflow. It helps the team test the venture concept.</p><form class="card" method="post" action="/feedback"><label>Name (optional)<input name="name"></label><label>Email (optional)<input name="email" type="email"></label><label>You are a…<select name="role"><option>Student</option><option>Business owner</option><option>Employer</option><option>University staff</option><option>Other</option></select></label><label>How useful is the concept?<select name="score"><option value="5">5 — Very useful</option><option value="4">4</option><option value="3">3</option><option value="2">2</option><option value="1">1 — Not useful</option></select></label><label>What would make SkillProof more useful or trustworthy?<textarea name="message" required></textarea></label><button class="btn big">Submit feedback</button></form></section>'''; self.send_html(page('Feedback',body,u))

    def save_feedback(self):
        d=self.parse_body(); msg=d.get('message','').strip();
        if not msg:return self.send_error(400)
        conn=db(); conn.execute('INSERT INTO feedback(name,email,role,score,message,created_at) VALUES(?,?,?,?,?,?)',(d.get('name','').strip(),d.get('email','').strip(),d.get('role',''),int(d.get('score','5')),msg,now_iso())); conn.commit(); conn.close(); self.send_html(page('Thank you','<section class="card success"><h1>Thanks for the feedback.</h1><p>Your response has been saved to the SkillProof database.</p><a class="btn" href="/">Back to SkillProof</a></section>',self.current_user()))


if __name__=='__main__':
    init_db()
    print(f'SkillProof running on http://127.0.0.1:{PORT}')
    ThreadingHTTPServer(('0.0.0.0',PORT),App).serve_forever()
