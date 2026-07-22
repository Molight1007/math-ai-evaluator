-- 这是一个 Lean 4 示例文件
-- 用法: 双击 leanrun.bat，或直接用 Cursor 打开本文件（保存即自动编译、实时报红）

def greet (name : String) : String :=
  s!"Hello, {name}!"

def main : IO Unit := do
  let msg := greet "Lean 4.31.0"
  IO.println msg
  -- 证明示例：0 + 1 = 1（命题可直接在 IO 中 println，Lean 会显示其证明项）
  have h : 0 + 1 = 1 := rfl
  IO.println "check 0+1=1 成立"
  -- 用 #guard 验证（脚本模式下通过）
  let _ : 0 + 1 = 1 := h
  pure ()
