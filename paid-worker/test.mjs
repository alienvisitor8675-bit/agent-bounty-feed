import w from "./worker.js";
const r1 = await w.fetch(new Request("https://x.example/v1/bounties?min_usd=2"));
console.log(r1.status, (await r1.text()).slice(0, 400));
const r2 = await w.fetch(new Request("https://x.example/"));
console.log(r2.status, await r2.text());
