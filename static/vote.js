let current = { player1: null, player2: null };
let busy = false;

function setPhoto(wrapEl, url) {
  wrapEl.innerHTML = '';
  wrapEl.classList.toggle('has-placeholder', !url);
  const img = document.createElement('img');
  img.src  = url || '/static/user.svg';
  img.className = url ? 'photo-real' : 'photo-placeholder';
  wrapEl.appendChild(img);
}

// Safe: uses DOM methods, never innerHTML with untrusted data
function setName(el, tag) {
  el.innerHTML = '';
  const i = tag.indexOf('#');
  if (i === -1) {
    el.textContent = tag;
    return;
  }
  const name = document.createElement('span');
  name.className = 'bt-name';
  name.textContent = tag.slice(0, i);

  const hash = document.createElement('span');
  hash.className = 'bt-hash';
  hash.textContent = '#' + tag.slice(i + 1);

  el.appendChild(name);
  el.appendChild(hash);
}

async function loadPair() {
  if (busy) return;
  const arena = document.getElementById('arena');
  arena.classList.add('loading');
  document.getElementById('card1').classList.remove('winner', 'loser');
  document.getElementById('card2').classList.remove('winner', 'loser');
  document.getElementById('win1').textContent = '';
  document.getElementById('win2').textContent = '';

  try {
    const res  = await fetch('/api/pair');
    const data = await res.json();
    current = data;

    setPhoto(document.getElementById('wrap1'), data.player1.image_url);
    setName(document.getElementById('name1'), data.player1.battletag);
    document.getElementById('team1').textContent = data.player1.team;

    setPhoto(document.getElementById('wrap2'), data.player2.image_url);
    setName(document.getElementById('name2'), data.player2.battletag);
    document.getElementById('team2').textContent = data.player2.team;
  } catch (e) {
    console.error(e);
  } finally {
    arena.classList.remove('loading');
  }
}

async function castVote(num) {
  if (busy || !current.player1) return;
  busy = true;

  document.getElementById('card' + num).classList.add('winner');
  document.getElementById('card' + (num === 1 ? 2 : 1)).classList.add('loser');

  const winnerId = num === 1 ? current.player1.id : current.player2.id;
  const loserId  = num === 1 ? current.player2.id : current.player1.id;

  try {
    await fetch('/api/vote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ winner_id: winnerId, loser_id: loserId }),
    });
    document.getElementById('win' + num).textContent = '✓ Winner';
    const c = document.getElementById('vote-count');
    c.textContent = parseInt(c.textContent.replace(/,/g, '')) + 1;
  } catch (e) {
    console.error(e);
  }

  setTimeout(() => { busy = false; loadPair(); }, 600);
}

document.getElementById('card1').addEventListener('click', () => castVote(1));
document.getElementById('card2').addEventListener('click', () => castVote(2));

loadPair();
