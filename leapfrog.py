"""Leapfrog: the frog-swapping puzzle.

Right-facing frogs (>) start on the left, left-facing frogs (<) on the right,
with one empty lily pad (_) between them. Swap the two groups.

Rules:
  - A frog only moves forward (> moves right, < moves left).
  - It may slide into an adjacent empty pad, or
  - jump over exactly one frog into the empty pad just beyond it.

Commands: type a pad number to move that frog, or
  h = hint, u = undo, r = restart, q = quit
"""

from collections import deque

RIGHT, LEFT, EMPTY = ">", "<", "_"


def start_board(n):
    return RIGHT * n + EMPTY + LEFT * n


def goal_board(n):
    return LEFT * n + EMPTY + RIGHT * n


def move_target(board, i):
    """Return where frog at index i would land, or None if it can't move."""
    frog = board[i]
    if frog == EMPTY:
        return None
    step = 1 if frog == RIGHT else -1
    for dist in (1, 2):
        j = i + step * dist
        if not 0 <= j < len(board):
            return None
        if board[j] == EMPTY:
            return j
    return None


def apply_move(board, i):
    j = move_target(board, i)
    cells = list(board)
    cells[i], cells[j] = cells[j], cells[i]
    return "".join(cells)


def legal_moves(board):
    return [i for i in range(len(board)) if move_target(board, i) is not None]


def solve(board, goal):
    """Breadth-first search for the shortest list of moves to the goal."""
    queue = deque([board])
    came_from = {board: None}
    while queue:
        cur = queue.popleft()
        if cur == goal:
            path = []
            while came_from[cur] is not None:
                prev, i = came_from[cur]
                path.append(i)
                cur = prev
            return path[::-1]
        for i in legal_moves(cur):
            nxt = apply_move(cur, i)
            if nxt not in came_from:
                came_from[nxt] = (cur, i)
                queue.append(nxt)
    return None


def show(board):
    print()
    print("  " + " ".join(f"{i + 1:>2}" for i in range(len(board))))
    print("  " + " ".join(f"{c:>2}" for c in board))
    print()


def ask_size():
    while True:
        raw = input("How many frogs per side? [3]: ").strip()
        if not raw:
            return 3
        if raw.isdigit() and 1 <= int(raw) <= 10:
            return int(raw)
        print("Please enter a number from 1 to 10.")


def play():
    print(__doc__)
    n = ask_size()
    goal = goal_board(n)
    best = n * n + 2 * n
    history = [start_board(n)]

    while True:
        board = history[-1]
        moves = len(history) - 1
        show(board)

        if board == goal:
            print(f"You solved it in {moves} moves! (Best possible: {best})")
            if input("Play again? [y/N]: ").strip().lower() == "y":
                n = ask_size()
                goal, best = goal_board(n), n * n + 2 * n
                history = [start_board(n)]
                continue
            return

        if not legal_moves(board):
            print("Stuck! No frog can move. Type u to undo or r to restart.")
        elif solve(board, goal) is None:
            print("(Heads up: this position can no longer be solved.)")

        cmd = input(f"Move {moves + 1} - pad number or h/u/r/q: ").strip().lower()

        if cmd == "q":
            return
        if cmd == "r":
            history = [start_board(n)]
        elif cmd == "u":
            if len(history) > 1:
                history.pop()
            else:
                print("Nothing to undo.")
        elif cmd == "h":
            path = solve(board, goal)
            if path is None:
                print("No solution from here. Try undoing.")
            else:
                print(f"Hint: move the frog on pad {path[0] + 1} "
                      f"({len(path)} moves left with perfect play).")
        elif cmd.isdigit() and 1 <= int(cmd) <= len(board):
            i = int(cmd) - 1
            if move_target(board, i) is None:
                print("That frog can't move.")
            else:
                history.append(apply_move(board, i))
        else:
            print("Didn't understand that.")


if __name__ == "__main__":
    try:
        play()
    except (KeyboardInterrupt, EOFError):
        print()
