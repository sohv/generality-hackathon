"""Keep voluntary submissions, resource limits, and provider errors distinct."""
import argparse
import json
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.batch / "manifest.json").read_text())
    events_path = args.batch / "operator_events.json"
    pauses = json.loads(events_path.read_text()) if events_path.exists() else []
    rows=[]
    for n in manifest["sizes"]:
        directory=args.batch/f"n{n:04d}"/f"n{n:04d}"
        if not (directory/"result.json").exists():
            continue
        result=json.loads((directory/"result.json").read_text())
        kinds={"submitted":0,"turn_limit":0,"time_limit":0,"token_limit":0,"cost_limit":0,
               "operator_pause_timeout":0,"request_timeout":0,"provider_error":0,
               "cancelled":0,"other_error":0,"stopped_without_submission":0}
        for name, row in result["agents"].items():
            detail=(str(row.get("limit") or "")+" "+str(row.get("error") or "")).lower()
            if row.get("submitted"):
                kinds["submitted"]+=1
            elif "turn limit" in detail:
                kinds["turn_limit"]+=1
            elif "time limit" in detail:
                kinds["time_limit"]+=1
            elif "token limit" in detail:
                kinds["token_limit"]+=1
            elif "cost limit" in detail:
                kinds["cost_limit"]+=1
            elif "attempttimeouterror" in detail:
                completed = datetime.fromisoformat(row["completed_at"])
                near_resume = any(n in p["affected_team_sizes"] and
                                  abs((completed - datetime.fromisoformat(p["resumed_at_utc"])).total_seconds()) < 5
                                  for p in pauses)
                kinds["operator_pause_timeout" if near_resume else "request_timeout"]+=1
            elif any(k in detail for k in ("openairesponseerror","apiconnectionerror","apierror","ratelimiterror")):
                kinds["provider_error"]+=1
            elif "cancelled" in detail:
                kinds["cancelled"]+=1
            elif row.get("error"):
                kinds["other_error"]+=1
            else:
                kinds["stopped_without_submission"]+=1
        rows.append({"agents":n,**kinds})
    (args.batch/"completion_diagnostics.json").write_text(json.dumps(rows,indent=2))
    print(json.dumps(rows,indent=2))


if __name__ == "__main__":
    main()
