import Link from "next/link";

export default function NotFound() { return <main className="dashboard-shell"><div className="panel"><h1>Not found</h1><p>This resource does not exist or is not available to your account.</p><Link className="button" href="/">Back to investigations</Link></div></main>; }
