import { Link } from 'react-router-dom';

export function Brand() {
  return (
    <Link className="brand" to="/meetings" aria-label="返回会议库">
      <span className="brand-logo" aria-hidden="true">
        <img src="/brand/xgimi-logo.jpg" alt="" />
      </span>
      <span className="brand-title">极米离线纪要助手</span>
    </Link>
  );
}
