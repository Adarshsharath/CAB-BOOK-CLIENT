const tripForm=document.querySelector('#booking form');
if(tripForm){
 const end=document.getElementById('return');
 function tripChanged(){end.hidden=tripForm.trip.value!=='Round trip';end.querySelector('input').required=!end.hidden}
 tripForm.addEventListener('change',tripChanged);tripChanged();
 document.querySelectorAll('[data-dest]').forEach(button=>button.onclick=()=>{tripForm.pickup.value='Bengaluru City Railway Station';tripForm.drop.value=button.dataset.dest;tripForm.dispatchEvent(new Event('landmarks-changed'));tripForm.trip.value=button.dataset.dest.includes('Airport')?'Airport':'One way';tripChanged();tripForm.date.focus();document.querySelector('#booking').scrollIntoView()});
}
const filter=document.querySelector('#fuel');
if(filter)filter.onchange=()=>{const cards=[...document.querySelectorAll('.offer')];cards.forEach(el=>el.hidden=filter.value!=='All fuels'&&el.dataset.fuel!==filter.value);if(!cards.some(el=>!el.hidden&&el.querySelector('input').checked))cards.find(el=>!el.hidden).querySelector('input').checked=true};
const search=document.querySelector('#search');if(search)search.oninput=()=>document.querySelectorAll('.entry').forEach(el=>el.hidden=!el.textContent.toLowerCase().includes(search.value.toLowerCase()));
const trace = document.querySelector('#road-trace');
if (trace) {
  const route = JSON.parse(trace.dataset.line);
  if (route.length > 1) {
    const longitudeFactor = Math.cos(route[0][1] * Math.PI / 180);
    const coords = route.map(([lon, lat]) => [lon * longitudeFactor, -lat]);
    const minX = Math.min(...coords.map(p => p[0]));
    const minY = Math.min(...coords.map(p => p[1]));
    const width = Math.max(...coords.map(p => p[0])) - minX;
    const height = Math.max(...coords.map(p => p[1])) - minY;
    const scale = Math.min(404 / (width || 0.00001), 126 / (height || 0.00001));
    const projected = coords.map(([x,y]) => [
      (440 - width * scale) / 2 + (x - minX) * scale,
      (156 - height * scale) / 2 + (y - minY) * scale
    ]);
    function draw(tag, attributes) {
      const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key,value] of Object.entries(attributes)) element.setAttribute(key,value);
      trace.append(element);
    }
    const points = projected.map(pair => pair.map(n => n.toFixed(2)).join(',')).join(' ');
    draw('polyline', {points, class:'route-shadow'});
    draw('polyline', {points, class:'route-stroke', pathLength:1});
    [projected[0], projected.at(-1)].forEach(([cx,cy], i) => {
      draw('circle', {cx,cy,r:8,class:'route-halo'});
      draw('circle', {cx,cy,r:4,fill:i ? '#9dffe4' : '#fff'});
    });
  }
}

const motion = matchMedia('(prefers-reduced-motion: no-preference)');
if ('IntersectionObserver' in window && motion.matches) {
  const reveal = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        entry.target.classList.add('arrive');
        reveal.unobserve(entry.target);
      }
    }
  }, {threshold: 0.1});
  document.querySelectorAll('.route, .fleet article').forEach(card => reveal.observe(card));
}

if (matchMedia('(hover: hover) and (pointer: fine)').matches) {
  document.querySelectorAll('.route, .journey').forEach(surface => {
    surface.addEventListener('pointermove', event => {
      if (!motion.matches) return;
      const box = surface.getBoundingClientRect();
      surface.style.setProperty('--shine-x', ((event.clientX-box.left)/box.width*100)+'%');
      surface.style.setProperty('--shine-y', ((event.clientY-box.top)/box.height*100)+'%');
    });
  });
}
