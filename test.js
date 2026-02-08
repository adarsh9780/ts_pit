fetch("http://localhost:8000/alerts").then(r=>r.json()).then(d=>{
  console.log("keys:", Object.keys(d[0]||{}));
  console.log("id samples:", d.slice(0,5).map(x => x.id));
  console.log("possible alt ids:", d.slice(0,2));
});
fetch("http://localhost:8000/config").then(r=>r.json()).then(c=>console.log("alerts mapping:", c.alerts));
