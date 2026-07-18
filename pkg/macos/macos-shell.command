#!/bin/zsh -f

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PS1=$'%F{cyan}hyops%f:%F{blue}%~%f$ '

clear
printf '\033]0;HybridOps.Core\007'
printf '\033[32mHybridOps.Core ready.\033[0m\n'

exec /bin/zsh -f -i
