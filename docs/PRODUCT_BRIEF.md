# Tevion Product Brief

## 1. Product definition

Tevion is a web/app product for creating personalized adult-male visual portraits. It helps a user express ambiguous aesthetic intent through natural language, visual choices, candidate comparison, and lightweight feedback. The system remembers the user's project-specific and long-term visual preferences and uses them to improve future generation decisions.

The initial visual goal is: **clearly adult men, approximately 22–28 by default, handsome, clean, fresh, youthful energy, natural anatomy, and deliberate cinematic/editorial lighting**. “Youthful” means adult freshness and vitality; it must never be resolved as a minor or childlike appearance.

## 2. The user problem

Users often know the feeling they want but do not know photography vocabulary or how to write a reliable prompt. A one-shot prompt box forces them to become prompt engineers and gives the product no structured learning signal.

Tevion changes the interaction from:

```text
write prompt → receive image → retry blindly
```

to:

```text
express intent → see the agent's interpretation → compare alternatives
→ point to what works → converge on a personal visual language
```

## 3. Target users for the first product slice

Primary: people and creators who repeatedly make, collect, or publish adult-male portrait imagery for avatars, social content, character references, moodboards, or visual series.

Not the first target: enterprise product advertising, a general-purpose image marketplace, or a local-model power-user console.

## 4. Core product objects

```text
User
└── Project
    ├── Persona / visual subject
    ├── Reference library
    ├── Sessions
    │   ├── User requests
    │   ├── Agent interpretations
    │   ├── Generation runs
    │   ├── Image versions
    │   └── Feedback events
    ├── Project memory
    └── Saved style recipes
```

A project is important: a temporary request must not pollute a user's general taste, and separate characters or content series need separate memories.

## 5. Primary experience

### Explore mode

Used to discover a direction. The system produces visibly different candidates across controlled dimensions such as facial mood, lighting, camera distance, styling, and background. Feedback should be one-click first: choose, like, reject, or “continue this direction.”

### Refine mode

Used after a candidate is selected. The user can say “keep the face and lighting, simplify the background” or select a specific dimension to change. Each iteration should change as few variables as possible and preserve parent/child version lineage.

### Understanding checkpoint

Before the first expensive generation, the agent shows a concise interpretation:

```text
adult male, 22–28
fresh and clean rather than childlike
soft directional light with dimensional shadows
waist-up editorial composition
low-saturation, simple layered background
```

The user can confirm, edit, or skip. This interaction is both a trust mechanism and a high-quality training signal.

## 6. Learning model

Tevion has three separate scopes:

1. **Session memory**: temporary instructions such as “keep this face, reduce the background.”
2. **Project/user preference**: stable choices inferred from repeated explicit selections and edits.
3. **Global strategy learning**: anonymized aggregate evidence used to compare prompt templates, candidate counts, critic policies, and provider settings.

Evidence strength should follow:

```text
explicit text feedback > tagged reason > selected candidate > download/edit > passive viewing
```

No global learning from private data without consent. No automatic model or strategy release from a single user's behavior.

## 7. North-star metric

**Personalized session success rate**: the percentage of completed generation sessions in which the user accepts a candidate, with the change from a non-personalized baseline tracked separately.

Supporting metrics:

- time and number of rounds to accepted result;
- candidate selection and feedback completion rate;
- second-session acceptance rate;
- average retries and cost per accepted result;
- preference prediction quality;
- rate of users invoking a saved visual memory.

## 8. Product risks

- “Youthful” can become an age-ambiguous instruction: always make adulthood explicit.
- Feedback can become work: default to one-click comparisons and ask for detail selectively.
- API quality can dominate the product: keep providers replaceable and measure strategy separately.
- Learning can become invisible or creepy: show what was remembered, why, and provide delete/temporary controls.
- A broad platform can dilute the initial value: keep the first goal narrow until repeated use is proven.
