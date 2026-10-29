import { FlaskConical } from "lucide-react";

import { Tag } from "@/components/ui/tag";

const DEFAULT_HINT: Record<string, string> = {
  "simulated filing": "A structured packet only. Nothing is sent to any real payment network or insurer.",
  "simulated seller": "A rules engine in the demo world. This is not a real airline or fare negotiation.",
  "simulated SMS": "Messages come from the SMS simulator, not a real telephony provider.",
  "sandbox airline": "The airline site and its inventory are a deterministic sandbox.",
  "sandbox connector": "Token issuance and revocation are real; the connector behind it is fake.",
  seeded: "Illustrative history run through the real formula; not a measurement.",
};

export function SimulatedBadge({ label = "simulated", hint }: { label?: string; hint?: string }) {
  return (
    <Tag tone="sim" title={hint ?? DEFAULT_HINT[label]}>
      <FlaskConical />
      {label}
    </Tag>
  );
}
