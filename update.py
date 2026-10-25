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
    if not t or t < TODAY-dt.timedelta(days=21) or t>TODAY+dt.timedelta(days=470): return None
    if not home or not away: return None
    return {'source':source,'team':code,'id':str(sid),'start':t.isoformat(),'home':home,'away':away,'competition':competition,'url':url,'status':status, 'scores': None, 'venue': None}

# Sports and ESPN abbreviations are NOT consistently named across leagues.
# Candidate team lookup is exact-name/alias-based rather than grabbing the first fuzzy result.
TARGETS={
'PFC-M': ('Paris FC (men)', [('soccer','fra.1')], ['Paris FC']),
'PFC-W': ('Paris FC (women)', [('soccer','fra.fem'),('soccer','fra.1.f')], ['Paris FC','Paris FC Women']),
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
        st=((x.get('status') or c.get('status') or {}).get('type') or {}).get('name','scheduled')
        obj=event('ESPN',code,x.get('id'),x.get('date') or c.get('date'),home,away,league,x.get('links',[{}])[0].get('href',''),st)
        if obj:
            venue=c.get('venue') or x.get('venue') or {}
            obj['venue'] = (venue.get('fullName') or venue.get('name')) if isinstance(venue,dict) else None
            score_by_side={}
            for side in sides:
                which=side.get('homeAway')
                val=side.get('score')
                if isinstance(val,dict): val=val.get('value',val.get('displayValue'))
                if which in ('home','away') and val is not None:
                    try: score_by_side[which]=int(float(val))
                    except (ValueError,TypeError): pass
            if ((st.lower() in ('status_final','final','status_full_time','full time')) or ((x.get('status') or c.get('status') or {}).get('type') or {}).get('completed') is True) and len(score_by_side)==2:
                obj['scores']=score_by_side
            result.append(obj)
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
    start=(TODAY-dt.timedelta(days=21)).date().isoformat()
    end=(TODAY+dt.timedelta(days=470)).date().isoformat()
    url='https://statsapi.mlb.com/api/v1/schedule?'+urllib.parse.urlencode({'sportId':1,'teamId':143,'startDate':start,'endDate':end,'hydrate':'team'})
    data=get(url)
    output=[]
    for day in (data or {}).get('dates',[]):
        for game in day.get('games',[]):
            h=game.get('teams',{}).get('home',{}).get('team',{}).get('name')
            a=game.get('teams',{}).get('away',{}).get('team',{}).get('name')
            item=event('MLB','PHILLIES',game.get('gamePk'),game.get('gameDate'),h,a,'MLB',f"https://www.mlb.com/gameday/{game.get('gamePk')}")
            if item:
                item['venue'] = (game.get('venue') or {}).get('name')
                if game.get('status',{}).get('abstractGameState','').lower() == 'final' or game.get('status',{}).get('detailedState','').lower().startswith('final'):
                    hscore=game.get('teams',{}).get('home',{}).get('score')
                    ascore=game.get('teams',{}).get('away',{}).get('score')
                    if hscore is not None and ascore is not None: item['scores']={'home':int(hscore),'away':int(ascore)}
                output.append(item)
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
                if n:
                    place_raw=team.get('placeName',{})
                    city=place_raw.get('default','') if isinstance(place_raw,dict) else str(place_raw or '')
                    if city and city.casefold() not in n.casefold():
                        return NHL_NAMES.get(city,city+' '+n)
                    return n
                place=team.get('placeName',{})
                if isinstance(place,dict): place=place.get('default','')
                return NHL_NAMES.get(place,place) or team.get('abbrev','')
            item=event('NHL','FLYERS',game.get('id'),game.get('startTimeUTC'),name(game.get('homeTeam',{})),name(game.get('awayTeam',{})),'NHL',f"https://www.nhl.com/gamecenter/{game.get('id')}")
            if item:
                place=game.get('venue',{})
                item['venue'] = place.get('default') if isinstance(place,dict) else (place if isinstance(place,str) else None)
                if game.get('gameState')=='OFF' and game.get('homeTeam',{}).get('score') is not None and game.get('awayTeam',{}).get('score') is not None:
                    item['scores']={'home':int(game['homeTeam']['score']),'away':int(game['awayTeam']['score'])}
                output.append(item)
    return output

# Optional official team feeds, when publicly available as ICS URLs.
# Add validated URLs to feeds.json. Events are kept even when ESPN lacks them.
def ical_unfold(s): return re.sub(r'\r?\n[ \t]', '', s)

def parse_external_ics(code,url):
    """Ingest a club ICS only if its teams, home/away and kickoff are unambiguous.

    A club-supplied calendar download is not necessarily a live subscription.
    Ambiguous rows are ignored rather than polluting the combined calendar.
    """
    from zoneinfo import ZoneInfo
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA['User-Agent']}),timeout=25) as r:
            s=ical_unfold(r.read().decode('utf-8-sig'))
        if 'BEGIN:VCALENDAR' not in s:
            raise ValueError('not an iCalendar document')
    except Exception as ex:
        ERRORS.append(f'Official team feed failed {code}: {str(ex)[:130]}')
        return []
    output=[]
    for block in s.split('BEGIN:VEVENT')[1:]:
        lines=block.split('END:VEVENT')[0].splitlines()
        fields={}; tzid=None
        for line in lines:
            if ':' not in line: continue
            k,v=line.split(':',1)
            fields[k.split(';')[0].upper()]=v
            if k.upper().startswith('DTSTART;'):
                found=re.search(r'TZID=([^;:]+)',k,re.I)
                if found: tzid=found.group(1)
        val=fields.get('DTSTART','').strip()
        try:
            if re.fullmatch(r'\d{8}T\d{6}Z',val):
                start=dt.datetime.strptime(val,'%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc)
            elif re.fullmatch(r'\d{8}T\d{6}',val) and tzid:
                start=dt.datetime.strptime(val,'%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(tzid)).astimezone(dt.timezone.utc)
            else: continue
        except (ValueError,KeyError): continue
        title=fields.get('SUMMARY','').replace('\\,',',').replace('\\n',' ').strip()
        # Parse only a genuinely two-sided fixture. Do not create fake
        # opponents from unstructured titles or team-only reminders.
        pair=re.split(r'\s+(?:vs\.?|v\.?|versus|@|at)\s+',title, maxsplit=1,flags=re.I)
        if len(pair)!=2: continue
        left,right=[re.sub(r'\s+\([^)]*\)$','',v).strip() for v in pair]
        if not left or not right: continue
        away_marker=bool(re.search(r'\s+(?:@|at)\s+',title,re.I))
        home,away=(right,left) if away_marker else (left,right)
        aliases=TARGETS[code][2]
        is_member=lambda n:any(equal_name(n,[alias]) or (code=='UNION' and equal_name(n,['Union','Philadelphia'])) for alias in aliases)
        if not (is_member(home) or is_member(away)): continue
        # Official Union feed is a fixture corroboration only; never create
        # synthetic results from a score-like string in the title.
        obj=event('Official feed',code,fields.get('UID') or title+'|'+val,start,home,away,'Official club calendar',url)
        if obj:
            loc=fields.get('LOCATION','').replace('\\,',',').strip()
            obj['venue']=loc or None
            output.append(obj)
    if not output:
        ERRORS.append(f'Official feed {code}: ICS downloaded but no unambiguous team fixtures parsed; ESPN/seed fixtures preserved')
    return output


def norm_name(value):
    x=re.sub(r'[^a-z0-9]+','',str(value).casefold())
    for initial,canonical in [('parisfootballclub','parisfc'),('parisfcwomen','parisfc'),('parisfcfemmes','parisfc'),('philadelphia76ers','76ers'),('philadelphiasixers','76ers'),('philadelphiaeagles','eagles'),('philadelphiaflyers','flyers'),('philadelphiaphillies','phillies'),('philadelphiaunion','union'),('liverpoolfc','liverpool'),('unitedstates','usa')]:
        if x==initial: return canonical
    return x

def similarity(a,b):
    a,b=norm_name(a),norm_name(b)
    if a==b: return 1
    return difflib.SequenceMatcher(None,a,b).ratio()

def match(a,b):
    if a['team']!=b['team']:return False
    # Provider IDs are stable even after a fixture is rescheduled.
    if a['source']==b['source'] and a['id']==b['id']:return True
    # Cross-source matching requires close dates. A moved game with the same provider ID
    # was already matched above. Never combine separate home/away fixtures.
    if abs((iso(a['start'])-iso(b['start'])).total_seconds())>36*3600:return False
    if a['source']=='Official feed' or b['source']=='Official feed':
        # Official feed's title must actually contain both opponents; don't merge without evidence.
        text=(a if a['source']=='Official feed' else b)['home'].casefold()
        structured=b if a['source']=='Official feed' else a
        return (team_names_equal(a['home'],b['home'],a['team']) and team_names_equal(a['away'],b['away'],a['team']))
    return team_names_equal(a['home'],b['home'],a['team']) and team_names_equal(a['away'],b['away'],a['team'])

def team_names_equal(a,b,code):
    # Canonical full names let ESPN and league sources merge the same fixture.
    a,b=short_name(a,code),short_name(b,code)
    if norm_name(a)==norm_name(b):return True
    if code=='FLYERS':
        a=NHL_NAMES.get(a,a); b=NHL_NAMES.get(b,b)
        return norm_name(a)==norm_name(b)
    # Do not merge distinct opponents on fuzzy similarity alone.
    return False

# Full city + franchise names for North American teams. The followed team comes
# first in every calendar title, whether at home or away.
SELF={'PFC-M':'Paris FC (M)','PFC-W':'Paris FC (W)','LFC':'Liverpool FC',
      'UNION':'Philadelphia Union','FRA-M':'France','FRA-W':'France',
      'USA-M':'USA','USA-W':'USA','EAGLES':'Philadelphia Eagles',
      'SIXERS':'Philadelphia 76ers','FLYERS':'Philadelphia Flyers',
      'PHILLIES':'Philadelphia Phillies'}
NAMES={'PARIS FC':'Paris FC','PARIS FOOTBALL CLUB':'Paris FC',
       'PARIS FC WOMEN':'Paris FC (W)','PARIS FC FÉMININES':'Paris FC (W)',
       'LIVERPOOL':'Liverpool FC','LIVERPOOL FC':'Liverpool FC',
       'FRANCE':'France','UNITED STATES':'USA','USA':'USA'}
# NHL API may provide only the city; resolve safely with known names.
NHL_NAMES={
 'Anaheim':'Anaheim Ducks','Boston':'Boston Bruins','Buffalo':'Buffalo Sabres',
 'Calgary':'Calgary Flames','Carolina':'Carolina Hurricanes','Chicago':'Chicago Blackhawks',
 'Colorado':'Colorado Avalanche','Columbus':'Columbus Blue Jackets','Dallas':'Dallas Stars',
 'Detroit':'Detroit Red Wings','Edmonton':'Edmonton Oilers','Florida':'Florida Panthers',
 'Los Angeles':'Los Angeles Kings','Minnesota':'Minnesota Wild','Montréal':'Montréal Canadiens',
 'Montreal':'Montréal Canadiens','Nashville':'Nashville Predators','New Jersey':'New Jersey Devils',
 'New York Islanders':'New York Islanders','New York Rangers':'New York Rangers',
 'Ottawa':'Ottawa Senators','Philadelphia':'Philadelphia Flyers','Pittsburgh':'Pittsburgh Penguins',
 'San Jose':'San Jose Sharks','Seattle':'Seattle Kraken','St. Louis':'St. Louis Blues',
 'Tampa Bay':'Tampa Bay Lightning','Toronto':'Toronto Maple Leafs','Utah':'Utah Mammoth',
 'Vancouver':'Vancouver Canucks','Vegas':'Vegas Golden Knights','Washington':'Washington Capitals',
 'Winnipeg':'Winnipeg Jets'}

def short_name(name,code=None):
    name=str(name).strip()
    k=name.upper()
    if k in ('PARIS FC','PARIS FOOTBALL CLUB') and code in ('PFC-M','PFC-W'):
        return SELF[code]
    if k in NAMES:return NAMES[k]
    if code=='FLYERS':return NHL_NAMES.get(name,name)
    if code in ('EAGLES','SIXERS','PHILLIES','UNION'):return name
    return name.replace(' Football Club','')

# Match-specific verified broadcaster database; no extrapolation from league TV rights.
# Each entry must identify country, actual channel/platform, and a public URL
# identifying the individual fixture. Blank entries mean no confirmed broadcaster.
BROADCAST_PATH = ROOT/'verified_broadcasts.json'
try:
    VERIFIED_BROADCASTS=json.loads(BROADCAST_PATH.read_text(encoding='utf-8')) if BROADCAST_PATH.exists() else []
except (ValueError,OSError):
    VERIFIED_BROADCASTS=[]
    ERRORS.append('Invalid verified_broadcasts.json; broadcast notes left empty')

def fixture_key(e):
    # Date-keyed, team-ordered identity for broadcaster verification. A changed
    # kickoff date must be reviewed rather than inheriting a stale TV listing.
    return e['team']+'|'+iso(e['start']).date().isoformat()+'|'+norm_name(e['home'])+'|'+norm_name(e['away'])

def viewing(e):
    broadcasts=[]
    for row in VERIFIED_BROADCASTS:
        if row.get('fixture_key')!=fixture_key(e): continue
        country=row.get('country','').upper()
        platform=str(row.get('platform','')).strip()
        proof=str(row.get('source_url','')).strip()
        if country not in ('FR','US') or not platform or not proof.startswith('https://'):
            continue
        # Match-specific fixture confirmation is entered manually from a rights
        # holder, TV guide, federation, or official competition fixture page.
        broadcasts.append((country,platform,proof))
    lines=[]
    for country,label in [('FR','France'),('US','USA')]:
        entries=[(platform,proof) for c,platform,proof in broadcasts if c==country]
        if entries:
            lines.append(label+': '+', '.join(dict.fromkeys(p for p,_ in entries)))
            lines.extend('Source: '+proof for _,proof in entries)
    return '\n'.join(lines)

# Club/municipal sources establish the regular home ground, but for an
# exceptional neutral-venue fixture only a fixture-specific listing is trusted.
# https://parisfc.fr/acces-aux-stades/
# https://www.paris.fr/evenements/matchs-du-paris-fc-pour-la-saison-2025-2026-le-calendrier-complet-118012
HOME_STADIUM={'PFC-M':'Stade Jean Bouin, 20-40 avenue du Général Sarrail, 75016 Paris, France',
              'PFC-W':'Stade Sébastien-Charléty, 99 boulevard Kellermann, 75013 Paris, France'}

def venue_for(e,home_is_me):
    if e.get('venue'): return str(e['venue'])
    # Only fill a regular home location for confirmed domestic-league games;
    # do not assume that cup/European or neutral-site fixtures share the venue.
    league=(e.get('competition') or '').lower()
    if home_is_me and e['team'] in HOME_STADIUM and ('fra.1' in league or 'fra.fem' in league):
        return HOME_STADIUM[e['team']]
    return ''

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
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Personal Sports Calendar//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:Sports fixtures','X-WR-TIMEZONE:Europe/Paris','REFRESH-INTERVAL;VALUE=DURATION:PT6H','X-PUBLISHED-TTL:PT6H']
    duration={'EAGLES':4,'SIXERS':3,'FLYERS':3,'PHILLIES':3.5}
    for e in sorted(items,key=lambda x:x['start']):
        t=iso(e['start']); end=t+dt.timedelta(hours=duration.get(e['team'],2.25))
        uid=e.get('uid') or (re.sub('[^A-Za-z0-9_-]','',e['team'])+'-'+re.sub('[^A-Za-z0-9_-]','',e['source'])+'-'+re.sub('[^A-Za-z0-9_-]','',str(e['id']))+'@favorite-sports')
        home=short_name(e['home'],e['team']); away=short_name(e['away'],e['team'])
        mine=SELF[e['team']]
        # Specially labelled Paris FC teams must match the right male/female calendar.
        home_is_me=similarity(home,mine)>.85
        away_is_me=similarity(away,mine)>.85
        score=e.get('scores') or {}
        has_score=score.get('home') is not None and score.get('away') is not None
        if home_is_me and not away_is_me:
            first=f'{mine} {score["home"]}-{score["away"]}' if has_score else mine
            title=f'{first} {away}' if has_score else f'{first} vs {away}'
        elif away_is_me and not home_is_me:
            first=f'{mine} {score["away"]}-{score["home"]}' if has_score else mine
            title=f'{first} {home}' if has_score else f'{first} @ {home}'
        else:
            title=f'{away} @ {home}'  # only when a provider has incomplete team identity
        if 'cancel' in str(e.get('status','')).lower() or 'postpone' in str(e.get('status','')).lower():
            title='[POSTPONED/CANCELLED] '+title
        desc=viewing(e)
        venue=venue_for(e,home_is_me)
        lines+=['BEGIN:VEVENT',fold('UID:'+uid),'DTSTAMP:'+TODAY.strftime('%Y%m%dT%H%M%SZ'),'DTSTART:'+t.strftime('%Y%m%dT%H%M%SZ'),'DTEND:'+end.strftime('%Y%m%dT%H%M%SZ'),fold('SUMMARY:'+escaped(title)),fold('DESCRIPTION:'+escaped(desc)),*([fold('LOCATION:'+escaped(venue))] if venue else []),fold('URL:'+e['url']) if e['url'] else 'TRANSP:OPAQUE','END:VEVENT']
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
    # Seed fixture coverage from the checked October 2026 calendar. Live provider
    # fixtures win over seed entries, and seed entries remain visible during outages.
    seed_path=ROOT/'seed_fixtures.json'
    seed=json.loads(seed_path.read_text(encoding='utf-8')) if seed_path.exists() else []
    out.extend(e for e in seed if iso(e['start']) and iso(e['start']) >= TODAY-dt.timedelta(days=21))
    # Deduplicate identical events across ESPN competitions and years, and official feeds.
    seen=set(); unique=[]
    for e in sorted(out,key=lambda x:(x['source'] in ('ESPN','Seed'),x['source']=='Seed',x['start'])):
        k=(e['source'],e['team'],e['id'])
        if k in seen: continue
        seen.add(k)
        if any(match(e,x) for x in unique):continue
        unique.append(e)
    # Fill scores only from verified completed feeds; preserve those already
    # published when an upstream provider temporarily stops returning a result.
    # Existing fixture JSON is also used to maintain Apple Calendar UIDs.
    # Protect calendar against global upstream outage.
    previous=DOCS/'fixtures.json'
    old=json.loads(previous.read_text()) if previous.exists() else []
    by_team=defaultdict(list)
    for e in unique:by_team[e['team']].append(e)
    # Carry forward stable UIDs when equivalent game appears with a different provider.
    for team_events in by_team.values():
        for e in team_events:
            same=[o for o in old if match(e,o)]
            if same and not e.get('scores'):
                scored=next((o for o in same if o.get('scores')),None)
                if scored:e['scores']=scored['scores']
            if same: e['uid']=same[0].get('uid') or (re.sub('[^A-Za-z0-9_-]','',same[0]['team'])+'-'+re.sub('[^A-Za-z0-9_-]','',same[0]['source'])+'-'+re.sub('[^A-Za-z0-9_-]','',str(same[0]['id']))+'@favorite-sports')
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
    audit={'generated':TODAY.isoformat(),'count':count,'total':len(result),'paris_venue_known':sum(bool(venue_for(e,similarity(short_name(e['home'],e['team']),SELF[e['team']])>.85)) for e in result if e['team'] in ('PFC-M','PFC-W')),'matches_with_verified_broadcast':sum(bool(viewing(e)) for e in result),'conflicts':conflicts,'errors':ERRORS,
           'explanation':'Providers are not exhaustive. Missing on a provider does not imply cancelled. Club calendars need validated direct ICS URLs in feeds.json.'}
    (DOCS/'audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Published:',len(result),'events. Conflicts:',len(conflicts),'fetch notes:',len(ERRORS))
    print('By team:',count)

if __name__=='__main__':main()
