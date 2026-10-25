#!/usr/bin/env python3
"""Publish subscribed sports calendar, plus source-comparison audit.
No keys required. ESPN endpoints are unofficial and can change.
"""
import datetime as dt
import difflib
import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / 'docs'
DOCS.mkdir(exist_ok=True)
TODAY = dt.datetime.now(dt.timezone.utc)
UA = {'User-Agent': 'SportsCalendar/1.0 personal weekly schedule client', 'Accept': 'application/json'}
ERRORS=[]

def get(url):
    try:
        req=urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req,timeout=25) as r:
            return json.load(r)
    except Exception as e:
        ERRORS.append(f'{url}: {str(e)[:180]}')
        return None

def iso(s):
    if not s: return None
    try: return dt.datetime.fromisoformat(str(s).replace('Z','+00:00')).astimezone(dt.timezone.utc)
    except (ValueError,TypeError): return None

def event(source, code, sid, start, home, away, competition='', url='', status='scheduled'):
    t=iso(start)
    if not t or t < TODAY-dt.timedelta(days=2) or t>TODAY+dt.timedelta(days=470): return None
    if not home or not away: return None
    return {'source':source,'team':code,'id':str(sid),'start':t.isoformat(),'home':home,'away':away,'competition':competition,'url':url,'status':status}

# Sports and ESPN abbreviations are NOT consistently named across leagues.
# Candidate team lookup is exact-name/alias-based rather than grabbing the first fuzzy result.
TARGETS={
'PFC-M': ('Paris FC (men)', [('soccer','fra.1')], ['Paris FC']),
'PFC-W': ('Paris FC (women)', [('soccer','fra.fem')], ['Paris FC','Paris FC Women']),
'LFC': ('Liverpool FC', [('soccer','eng.1'),('soccer','uefa.champions'),('soccer','eng.league_cup'),('soccer','eng.fa')], ['Liverpool','Liverpool FC']),
'UNION': ('Philadelphia Union', [('soccer','usa.1')], ['Philadelphia Union']),
'FRA-M': ('France men', [('soccer','uefa.nations'),('soccer','fifa.friendly'),('soccer','fifa.world')], ['France']),
'FRA-W': ('France women', [('soccer','fifa.friendly.w'),('soccer','fifa.world.w'),('soccer','uefa.weuro')], ['France']),
'USA-M': ('USA men', [('soccer','concacaf.nations.league'),('soccer','fifa.friendly'),('soccer','fifa.world')], ['United States','USA']),
'USA-W': ('USA women', [('soccer','fifa.friendly.w'),('soccer','fifa.world.w'),('soccer','concacaf.w.championship')], ['United States','USA']),
'EAGLES': ('Philadelphia Eagles', [('football','nfl')], ['Philadelphia Eagles']),
'SIXERS': ('Philadelphia 76ers', [('basketball','nba')], ['Philadelphia 76ers']),
'FLYERS': ('Philadelphia Flyers', [('hockey','nhl')], ['Philadelphia Flyers']),
'PHILLIES': ('Philadelphia Phillies', [('baseball','mlb')], ['Philadelphia Phillies']),
}
BASE='https://site.api.espn.com/apis/site/v2/sports'
CACHE={}

def teams(sport,league):
    key=(sport,league)
    if key not in CACHE:
        url=f'{BASE}/{sport}/{league}/teams?limit=1000'
        raw=get(url)
        entries=[]
        if raw:
            for item in raw.get('sports',[]):
                for l in item.get('leagues',[]):
                    for ent in l.get('teams',[]):
                        entries.append(ent.get('team',ent))
        CACHE[key]=entries
    return CACHE[key]

def equal_name(n,aliases):
    def clean(x): return re.sub('[^a-z0-9]','',x.casefold())
    return any(clean(n)==clean(a) for a in aliases)

def parse_espn(code, sport, league, raw):
    result=[]
    for x in (raw or {}).get('events',[]):
        c=(x.get('competitions') or [{}])[0]
        sides=c.get('competitors',[])
        home=next((i.get('team',{}).get('displayName') for i in sides if i.get('homeAway')=='home'),None)
        away=next((i.get('team',{}).get('displayName') for i in sides if i.get('homeAway')=='away'),None)
        st=x.get('status',{}).get('type',{}).get('name','scheduled')
        obj=event('ESPN',code,x.get('id'),x.get('date') or c.get('date'),home,away,league,x.get('links',[{}])[0].get('href',''),st)
        if obj: result.append(obj)
    return result

def espn_schedules():
    output=[]
    for code, (label, leagues, aliases) in TARGETS.items():
        for sport, league in leagues:
            choices=teams(sport,league)
            chosen=[i for i in choices if any(equal_name(str(i.get(k,'')),aliases) for k in ['displayName','name','shortDisplayName'])]
            if not chosen:
                ERRORS.append(f'ESPN roster lookup unresolved: {code} in {league}. No match was guessed.')
                continue
            teamid=chosen[0].get('id')
            for yr in (2026,2027):
                q=urllib.parse.urlencode({'season':yr,'limit':500})
                raw=get(f'{BASE}/{sport}/{league}/teams/{teamid}/schedule?{q}')
                output+=parse_espn(code,sport,league,raw)
    return output

# Official league endpoints supply an independent canonical match list.
def mlb_schedule():
    start=(TODAY-dt.timedelta(days=2)).date().isoformat()
    end=(TODAY+dt.timedelta(days=470)).date().isoformat()
    url='https://statsapi.mlb.com/api/v1/schedule?'+urllib.parse.urlencode({'sportId':1,'teamId':143,'startDate':start,'endDate':end,'hydrate':'team'})
    data=get(url)
    output=[]
    for day in (data or {}).get('dates',[]):
        for game in day.get('games',[]):
            h=game.get('teams',{}).get('home',{}).get('team',{}).get('name')
            a=game.get('teams',{}).get('away',{}).get('team',{}).get('name')
            item=event('MLB','PHILLIES',game.get('gamePk'),game.get('gameDate'),h,a,'MLB',f"https://www.mlb.com/gameday/{game.get('gamePk')}")
            if item: output.append(item)
    return output

def nhl_schedule():
    output=[]
    # League API provides team schedules for complete seasons.
    for season in ('20262027','20272028'):
        data=get(f'https://api-web.nhle.com/v1/club-schedule-season/PHI/{season}')
        for game in (data or {}).get('games',[]):
            h=game.get('homeTeam',{}).get('placeName',{})
            a=game.get('awayTeam',{}).get('placeName',{})
            def name(team):
                n=team.get('name',{})
                if isinstance(n,dict): n=n.get('default','')
                if n: return n
                place=team.get('placeName',{})
                if isinstance(place,dict): place=place.get('default','')
                return place or team.get('abbrev','')
            item=event('NHL','FLYERS',game.get('id'),game.get('startTimeUTC'),name(game.get('homeTeam',{})),name(game.get('awayTeam',{})),'NHL',f"https://www.nhl.com/gamecenter/{game.get('id')}")
            if item: output.append(item)
    return output

# Optional official team feeds, when publicly available as ICS URLs.
# Add validated URLs to feeds.json. Events are kept even when ESPN lacks them.
def ical_unfold(s): return re.sub(r'\r?\n[ \t]', '', s)

def parse_external_ics(code,url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA['User-Agent']}),timeout=25) as r:
            s=ical_unfold(r.read().decode('utf-8-sig'))
    except Exception as ex:
        ERRORS.append(f'Official team feed failed {code}: {str(ex)[:100]}')
        return []
    output=[]
    for b in s.split('BEGIN:VEVENT')[1:]:
        lines=b.split('END:VEVENT')[0].splitlines()
        fields={}
        for ln in lines:
            if ':' in ln:
                k,v=ln.split(':',1); fields[k.split(';')[0]]=v
        val=fields.get('DTSTART','')
        if re.fullmatch(r'\d{8}T\d{6}Z',val): start=dt.datetime.strptime(val,'%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc)
        elif re.fullmatch(r'\d{8}T\d{6}',val):
            # Without a TZID, local time is ambiguous: do not fabricate UTC conversion.
            continue
        else: continue
        title=fields.get('SUMMARY','').replace('\\,',',').replace('\\n',' ')
        # External ICS title may have no clear home/away distinction.
        obj=event('Official feed',code,fields.get('UID',title),start,title,'(opponent in title)', 'Official club calendar',url)
        if obj: output.append(obj)
    return output


def identity(e):
    # ESPN/official league usually share recognizable opponents but not identical spelling.
    # UTC date tolerance accounts for midnight and reporting date differences.
    return e['team']

def similarity(a,b):
    def normal(s):
        return re.sub('[^a-z0-9]','',s.casefold().replace('philadelphia','').replace('flyers','').replace('phillies',''))
    return difflib.SequenceMatcher(None,normal(a),normal(b)).ratio()

def match(a,b):
    if a['team']!=b['team'] or abs((iso(a['start'])-iso(b['start'])).total_seconds())>36*3600:return False
    if a['source']=='Official feed' or b['source']=='Official feed':
        return False  # no opponent normalization possible: do not falsely merge
    return similarity(a['home'],b['home'])>.68 and similarity(a['away'],b['away'])>.68


def escaped(v): return str(v).replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;')

def fold(s):
    # UTF-8 correct folding by byte length.
    acc=b''; chunks=[]
    for c in s:
        enc=c.encode('utf-8')
        if len(acc)+len(enc)>73:
            chunks.append(acc.decode('utf-8')); acc=b' '+enc
        else: acc+=enc
    if acc: chunks.append(acc.decode('utf-8'))
    return '\r\n'.join(chunks)

def to_ics(items):
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Personal Sports Calendar//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:Favorite Sports - live fixtures','X-WR-TIMEZONE:Europe/Paris','REFRESH-INTERVAL;VALUE=DURATION:PT6H','X-PUBLISHED-TTL:PT6H']
    duration={'EAGLES':4,'SIXERS':3,'FLYERS':3,'PHILLIES':3.5}
    for e in sorted(items,key=lambda x:x['start']):
        t=iso(e['start']); end=t+dt.timedelta(hours=duration.get(e['team'],2.25))
        # Persist source and ID; dates can change without duplicating events.
        uid=f"{re.sub('[^A-Za-z0-9_-]','',e['team'])}-{re.sub('[^A-Za-z0-9_-]','',e['source'])}-{re.sub('[^A-Za-z0-9_-]','',str(e['id']))}@favorite-sports"
        home=e['home']; away=e['away']
        label=TARGETS[e['team']][0]
        title=f'{label}: {home} vs {away}' if e['source']!='Official feed' else f'{label}: {home}'
        desc=f"Competition: {e['competition']}\nSource: {e['source']}\nSource URL: {e['url']}\nKickoff and TV rights may change. Viewer providers are not reliably known far in advance."
        lines+=['BEGIN:VEVENT',fold('UID:'+uid),'DTSTAMP:'+TODAY.strftime('%Y%m%dT%H%M%SZ'),'DTSTART:'+t.strftime('%Y%m%dT%H%M%SZ'),'DTEND:'+end.strftime('%Y%m%dT%H%M%SZ'),fold('SUMMARY:'+escaped(title)),fold('DESCRIPTION:'+escaped(desc)),fold('URL:'+e['url']) if e['url'] else 'TRANSP:OPAQUE','END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines)+'\r\n'

def main():
    espn=espn_schedules()
    official=mlb_schedule()+nhl_schedule()
    feeds_path=ROOT/'feeds.json'
    feeds=json.loads(feeds_path.read_text()) if feeds_path.exists() else {}
    for code,urls in feeds.items():
        if code not in TARGETS: continue
        for url in urls: official+=parse_external_ics(code,url)
    # Audit source conflicts. Official NHL/MLB wins when a match can be resolved.
    conflicts=[]; out=[]; matched=set()
    for a in official:
        relevant=[(j,b) for j,b in enumerate(espn) if match(a,b)]
        if relevant:
            j,b=min(relevant,key=lambda jb:abs((iso(a['start'])-iso(jb[1]['start'])).total_seconds()))
            matched.add(j)
            if abs((iso(a['start'])-iso(b['start'])).total_seconds())>15*60:
                conflicts.append({'team':a['team'],'official':a,'espn':b,'issue':'Kickoff difference >15 min; official schedule used'})
        out.append(a)
    for j,b in enumerate(espn):
        if j not in matched: out.append(b)
    # Deduplicate identical events across ESPN competitions and years, and official feeds.
    seen=set(); unique=[]
    for e in sorted(out,key=lambda x:(x['source']=='ESPN',x['start'])):
        k=(e['source'],e['team'],e['id'])
        if k in seen: continue
        seen.add(k)
        if any(match(e,x) for x in unique):continue
        unique.append(e)
    # Protect calendar against global upstream outage.
    previous=DOCS/'fixtures.json'
    old=json.loads(previous.read_text()) if previous.exists() else []
    by_team=defaultdict(list)
    for e in unique:by_team[e['team']].append(e)
    for e in old:
        if not by_team[e['team']] and iso(e['start']) and iso(e['start'])>TODAY:
            by_team[e['team']].append(e)
            ERRORS.append(f"{e['team']}: carried forward prior events because providers returned no fixtures")
    result=sum(by_team.values(),[])
    # Avoid republishing a totally empty calendar.
    if not result: raise SystemExit('No events: refusing to overwrite the published calendar')
    (DOCS/'sports.ics').write_text(to_ics(result),encoding='utf-8',newline='')
    previous.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    count={code:len(by_team[code]) for code in TARGETS}
    audit={'generated':TODAY.isoformat(),'count':count,'total':len(result),'conflicts':conflicts,'errors':ERRORS,
           'explanation':'Providers are not exhaustive. Missing on a provider does not imply cancelled. Club calendars need validated direct ICS URLs in feeds.json.'}
    (DOCS/'audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Published:',len(result),'events. Conflicts:',len(conflicts),'fetch notes:',len(ERRORS))
    print('By team:',count)

if __name__=='__main__':main()
