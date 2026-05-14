-- 잘못 시드된 pk-lf-playground 키 삭제
-- 재시작 시 LANGFUSE_INIT_* 가 올바른 키(pk-lf-533309e0...)로 재생성함
DELETE FROM api_keys WHERE public_key = 'pk-lf-playground';
