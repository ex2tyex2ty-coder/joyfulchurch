-- Only sound-specific objects and named Realtime policies are managed here.
CREATE TABLE IF NOT EXISTS public.sound_receivers (
    user_id uuid NOT NULL, topic text NOT NULL, expires_at double precision NOT NULL,
    PRIMARY KEY(user_id, topic)
);
ALTER TABLE public.sound_receivers ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON public.sound_receivers TO authenticated;
DROP POLICY IF EXISTS joyful_sound_own_receiver ON public.sound_receivers;
CREATE POLICY joyful_sound_own_receiver ON public.sound_receivers FOR SELECT TO authenticated
USING (user_id = (SELECT auth.uid()) AND expires_at > extract(epoch FROM now()));

DROP POLICY IF EXISTS joyful_sound_receive ON realtime.messages;
CREATE POLICY joyful_sound_receive ON realtime.messages FOR SELECT TO authenticated
USING (extension = 'broadcast' AND EXISTS (
    SELECT 1 FROM public.sound_receivers r
    WHERE r.user_id = (SELECT auth.uid()) AND r.topic = (SELECT realtime.topic())
      AND r.expires_at > extract(epoch FROM now())
));
-- Scope restrictive guard to sound topics, without altering unrelated channels.
DROP POLICY IF EXISTS joyful_sound_guard ON realtime.messages;
CREATE POLICY joyful_sound_guard ON realtime.messages AS RESTRICTIVE FOR SELECT TO authenticated
USING (realtime.topic() NOT LIKE 'sound:%' OR EXISTS (
    SELECT 1 FROM public.sound_receivers r
    WHERE r.user_id = (SELECT auth.uid()) AND r.topic = (SELECT realtime.topic())
      AND r.expires_at > extract(epoch FROM now())
));
DROP POLICY IF EXISTS joyful_sound_no_client_send ON realtime.messages;
CREATE POLICY joyful_sound_no_client_send ON realtime.messages AS RESTRICTIVE FOR INSERT TO authenticated
WITH CHECK (realtime.topic() NOT LIKE 'sound:%');

CREATE OR REPLACE FUNCTION public.joyful_sound_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE rid text; pid text; p record;
BEGIN
  IF TG_TABLE_NAME IN ('sound_requests', 'sound_thread_messages') THEN
    rid := NEW.room_id; pid := NEW.person_id;
  ELSIF TG_TABLE_NAME = 'sound_replies' THEN
    SELECT room_id, person_id INTO rid, pid FROM public.sound_requests WHERE id=NEW.request_id;
  ELSIF TG_TABLE_NAME = 'sound_people' THEN
    rid := NEW.room_id; pid := NEW.id;
  ELSE
    rid := NEW.id;
    FOR p IN SELECT id FROM public.sound_people WHERE room_id=rid LOOP
      PERFORM realtime.send('{}'::jsonb, 'changed', 'sound:person:' || p.id, true);
    END LOOP;
  END IF;
  -- Only an empty invalidation signal, never aliases, bodies or recovery tokens.
  PERFORM realtime.send('{}'::jsonb, 'changed', 'sound:room:' || rid, true);
  IF pid IS NOT NULL THEN
    PERFORM realtime.send('{}'::jsonb, 'changed', 'sound:person:' || pid, true);
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.joyful_sound_changed() FROM PUBLIC;
DROP TRIGGER IF EXISTS joyful_sound_requests_changed ON public.sound_requests;
CREATE TRIGGER joyful_sound_requests_changed AFTER INSERT OR UPDATE ON public.sound_requests
FOR EACH ROW EXECUTE FUNCTION public.joyful_sound_changed();
DROP TRIGGER IF EXISTS joyful_sound_replies_changed ON public.sound_replies;
CREATE TRIGGER joyful_sound_replies_changed AFTER INSERT ON public.sound_replies
FOR EACH ROW EXECUTE FUNCTION public.joyful_sound_changed();
DROP TRIGGER IF EXISTS joyful_sound_room_changed ON public.sound_rooms;
CREATE TRIGGER joyful_sound_room_changed AFTER UPDATE ON public.sound_rooms
FOR EACH ROW EXECUTE FUNCTION public.joyful_sound_changed();
DROP TRIGGER IF EXISTS joyful_sound_person_changed ON public.sound_people;
CREATE TRIGGER joyful_sound_person_changed AFTER UPDATE ON public.sound_people
FOR EACH ROW EXECUTE FUNCTION public.joyful_sound_changed();
DROP TRIGGER IF EXISTS joyful_sound_thread_changed ON public.sound_thread_messages;
CREATE TRIGGER joyful_sound_thread_changed AFTER INSERT ON public.sound_thread_messages
FOR EACH ROW EXECUTE FUNCTION public.joyful_sound_changed();
