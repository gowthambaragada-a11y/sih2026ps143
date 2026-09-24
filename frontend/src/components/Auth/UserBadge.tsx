import type { AuthUser } from "../../services/firebase";

interface Props {
  user: AuthUser;
  onSignOut: () => void;
}

export function UserBadge({ user, onSignOut }: Props) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-[#1e293b] bg-[#0f172a] py-1 pl-1 pr-2">
      {user.photoURL ? (
        <img
          src={user.photoURL}
          alt=""
          className="h-7 w-7 rounded-full object-cover ring-1 ring-[#1e293b]"
        />
      ) : (
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-[#06b6d4] to-[#0e7490] text-[11px] font-black text-[#062032]">
          {user.name.slice(0, 1).toUpperCase()}
        </div>
      )}
      <div className="hidden min-w-0 sm:block">
        <div className="truncate text-xs font-semibold text-[#e6f1f8]">{user.name}</div>
        <div className="truncate text-[10px] leading-tight text-[#8496ab]">
          {user.isGuest ? "Guest evaluator" : user.email}
        </div>
      </div>
      <button
        onClick={onSignOut}
        title="Sign out"
        className="ml-1 rounded-full border border-[#1e293b] px-2 py-1 text-[10px] font-semibold text-[#8496ab] transition hover:border-red-500/50 hover:text-red-300"
      >
        Sign out
      </button>
    </div>
  );
}