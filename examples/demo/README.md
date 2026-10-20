# Demo project

`make-demo.sh` builds `weather-cli`, a small Python CLI with typical Markdown drift: a README that
documents removed flags (`--fahrenheit`, `--forecast`) and the old `OWM_API_KEY` variable, an outdated
setup guide, a stale TODO list, an empty stub, a draft changelog, meeting notes and scattered agent
instructions. Six commits, fixed dates, same output every time.

```
./make-demo.sh ~/weather-cli
cd ~/weather-cli
libraryan init
```

Then compare `find . -name '*.md' -not -path './.git/*'` before and after, and read
`.libraryan/state/reports/latest.md`.
`libraryan uninstall` removes the hooks and the cron line again (the KB stays).
