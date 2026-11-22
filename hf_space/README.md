---
title: RIA AI Companion
emoji: 💗
colorFrom: pink
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: Web chat and admin dashboard for RIA (runs on a private VPS)
---

RIA web chat + admin dashboard. This Space is a stateless front end; all conversations and memories live on the
owner's private server and are accessed through an authenticated HTTPS API. Configure it with Space Secrets
(see `.env.example`). Open the Space's direct URL (`https://<user>-ria-ai-companion.hf.space`) rather than the
embedded huggingface.co view so login cookies work.
