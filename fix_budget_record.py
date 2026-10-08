with open('orchestra/agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the budget recording section
old = """            # Budget: record usage after each model call
            if self._budget_state and resp.total_tokens > 0:
                # estimate cost from usage (rough)
                prompt_tokens = getattr(resp, 'prompt_tokens', 0)
                completion_tokens = getattr(resp, 'completion_tokens', 0)
                # rough cost estimate: $0.001 per 1k tokens average
                cost_usd = (prompt_tokens + completion_tokens) / 1000 * 0.001
                violations = budget_guard().record_usage(
                    session_id=f"{self.provider.name}_{getattr(self.provider, 'model', 'unknown')}",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    model=resp.model,
                    category="",
                )
                if violations:
                    self._emit("budget_violation", violations=violations)
                    self.state.stopped_because = "budget_exceeded"
                    return self.state"""

new = """            # Budget: record usage after each model call
            if self._budget_state and resp.total_tokens > 0:
                # get prompt/completion tokens from response
                prompt_tokens = getattr(resp, 'prompt_tokens', 0)
                completion_tokens = getattr(resp, 'completion_tokens', 0)
                if prompt_tokens == 0 and completion_tokens == 0:
                    # rough split if not provided
                    prompt_tokens = resp.total_tokens // 2
                    completion_tokens = resp.total_tokens - prompt_tokens
                # rough cost estimate: $0.001 per 1k tokens average
                cost_usd = (prompt_tokens + completion_tokens) / 1000 * 0.001
                # use the agent's budget state directly
                self._budget_state.add_usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    model=resp.model,
                    category="",
                )
                violations = self._budget_state.check_limits()
                if violations:
                    self._emit("budget_violation", violations=violations)
                    self.state.stopped_because = "budget_exceeded"
                    return self.state"""

if old in content:
    content = content.replace(old, new)
    with open('orchestra/agent.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed budget recording')
else:
    print('NOT FOUND - searching...')
    # Debug
    idx = content.find('Budget: record usage')
    if idx >= 0:
        print(repr(content[idx:idx+500]))
    else:
        print('Keyword not found')

with open('orchestra/agent.py', 'w', encoding='utf-8') as f:
    f.write(content)