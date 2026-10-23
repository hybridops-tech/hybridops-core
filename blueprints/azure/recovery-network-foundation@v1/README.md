# Azure Recovery Network Foundation

This blueprint establishes an isolated network boundary for recovery workloads.
HybridOps owns the operation as one lifecycle:

1. validate the declared target;
2. establish the resource boundary;
3. establish the recovery network inside that boundary; and
4. retain evidence for both steps.

The dependency fixes creation and removal order. The shipped file is an
immutable reference default. Initialise an environment overlay before changing
the target name, location, address space or tags.

## Initialise the environment contract

```bash
hyops blueprint init \
  --env <env> \
  --ref azure/recovery-network-foundation@v1

hyops blueprint edit \
  --env <env> \
  --ref azure/recovery-network-foundation@v1
```

## Inspect

```bash
hyops blueprint validate \
  --env <env> \
  --ref azure/recovery-network-foundation@v1

hyops blueprint plan \
  --env <env> \
  --ref azure/recovery-network-foundation@v1
```

Neither command changes Azure resources.

## Deploy

```bash
hyops blueprint deploy \
  --env <env> \
  --ref azure/recovery-network-foundation@v1 \
  --execute
```

Deployment performs blueprint-level preflight before executing the ordered
steps. Run records remain under the selected HybridOps environment.

## Destroy

```bash
hyops blueprint destroy \
  --env <env> \
  --ref azure/recovery-network-foundation@v1 \
  --execute
```

Destroy runs the blueprint steps in reverse dependency order.
