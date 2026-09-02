/* ########### Logging ########### */
#include "log.h" /* from openssh */

#define D1(fmt, ...) logit("[MQ] " fmt, ##__VA_ARGS__)
#define D2(fmt, ...) debug("[MQ] " fmt, ##__VA_ARGS__)
#define D3(fmt, ...) debug2("[MQ] " fmt, ##__VA_ARGS__)

#ifdef HAVE_SHA2_H /* For the checksums */
#  include <sha2.h>
#else
#  include "openbsd-compat/sha2.h"
#endif

#include <ifaddrs.h>
#include <arpa/inet.h>
#include <net/if.h>
static char local_ip[INET_ADDRSTRLEN];
static char hostname[256];

#include <rabbitmq-c/tcp_socket.h> /* includes amqp.h */
#include <json-c/json.h>           /* For the JSON-formatted MQ message */
#include <uuid/uuid.h>             /* For uuid in the MQ message */

/* Default values */
#define UUID_STR_LEN	   37
#define LEGA_MQ_HEARTBEAT  3600

static const char* amqp_server_exception_string(amqp_rpc_reply_t r);
static const char* amqp_rpc_reply_string(amqp_rpc_reply_t r);

static amqp_bytes_t exchange = { .bytes = (void*)"amq.topic", .len = sizeof("amq.topic") - 1};
static amqp_bytes_t routing_key = { .bytes = (void*)"files.inbox", .len = sizeof("files.inbox") - 1};
static amqp_table_entry_t client_entries[3];
static amqp_table_t client_properties = { .num_entries = 3,
                                          .entries = client_entries }; /* conn_name + remote ip/username */
static char connection_name[1024];
static amqp_table_entry_t header_entries[4];
static amqp_table_t headers = { .num_entries = 0, .entries = header_entries }; // will get incremented


static void
mq_client_properties(void)
{
  extern char *__progname;
  /* Connection name */
  snprintf(connection_name, 1024, "%s <%s>", __progname, pw->pw_name);
  client_entries[0].key = amqp_cstring_bytes("connection_name");
  client_entries[0].value.kind = AMQP_FIELD_KIND_UTF8;
  client_entries[0].value.value.bytes = amqp_cstring_bytes(connection_name);

  /* Connection from IP */
  client_entries[1].key = amqp_cstring_bytes("remote_ip");
  client_entries[1].value.kind = AMQP_FIELD_KIND_UTF8;
  client_entries[1].value.value.bytes = amqp_cstring_bytes(client_addr);

  /* Connection from user */
  client_entries[2].key = amqp_cstring_bytes("remote_username");
  client_entries[2].value.kind = AMQP_FIELD_KIND_UTF8;
  client_entries[2].value.value.bytes = amqp_cstring_bytes(pw->pw_name);

  // Max header entries: 4

  /* remote ip in the message headers */
  header_entries[0].key = amqp_cstring_bytes("remote_ip");
  header_entries[0].value.kind = AMQP_FIELD_KIND_UTF8;
  header_entries[0].value.value.bytes = amqp_cstring_bytes(client_addr);

  /* remote username in the message headers */
  header_entries[1].key = amqp_cstring_bytes("remote_username");
  header_entries[1].value.kind = AMQP_FIELD_KIND_UTF8;
  header_entries[1].value.value.bytes = amqp_cstring_bytes(pw->pw_name);

  headers.num_entries = 2;

  /* Get the hostname: might fail if in chroot */
  if (gethostname(hostname, sizeof(hostname))) {
    D3("Error getting hostname: %s", strerror(errno));
  } else {
    header_entries[headers.num_entries].key = amqp_cstring_bytes("inbox_hostname");
    header_entries[headers.num_entries].value.kind = AMQP_FIELD_KIND_UTF8;
    header_entries[headers.num_entries].value.value.bytes = amqp_cstring_bytes(hostname);
    headers.num_entries++;
  }

  /* Machine IP in header */
  struct ifaddrs *ifaddr, *ifa;
  if (getifaddrs(&ifaddr) == -1) {
    D3("Error getifaddrs: %s", strerror(errno));
    return;
  }

  for (ifa = ifaddr; ifa != NULL; ifa = ifa->ifa_next) {
    if (ifa->ifa_addr == NULL)
      continue;

    // Skip loopback (127.0.0.1) and non-AF_INET (IPv4) addresses
    if (ifa->ifa_addr->sa_family == AF_INET) {
      struct sockaddr_in *addr = (struct sockaddr_in *)ifa->ifa_addr;
      if (strcmp(ifa->ifa_name, "lo") != 0) { // Skip loopback interface
	inet_ntop(AF_INET, &addr->sin_addr, local_ip, INET_ADDRSTRLEN);
	break;
      }
    }
  }
  freeifaddrs(ifaddr);

  header_entries[headers.num_entries].key = amqp_cstring_bytes("inbox_ip");
  header_entries[headers.num_entries].value.kind = AMQP_FIELD_KIND_UTF8;
  header_entries[headers.num_entries].value.value.bytes = amqp_cstring_bytes(local_ip);
  headers.num_entries++;
}

/* ================================================
 *
 *                For the connection
 *
 * ================================================ */
static amqp_connection_state_t mq_conn;
static int mq_conn_initialized = 0;

static int
mq_init(void)
{
  if(mq_conn_initialized) return 0;

  amqp_socket_t *mq_socket;

  /* initialize */
  mq_conn = amqp_new_connection();
  D2("Initializing AMQP socket");
  mq_socket = amqp_tcp_socket_new(mq_conn);
  if (!mq_socket) { D3("Error creating TCP socket"); return 1; }

  /* connect */
  D2("Connecting to message broker");
  int rc;

  if ( (rc = amqp_socket_open(mq_socket, "127.0.0.1", 5672)) ) {
    D1("Error opening TCP socket to \"localhost:5672\": %s", amqp_error_string2(rc));
    return 2;
  }
  
  amqp_rpc_reply_t amqp_ret;
  amqp_ret =
    amqp_login_with_properties(mq_conn,
			       "/", // %2F is for URLs 
			       1, /* limit number of channels */
			       AMQP_DEFAULT_FRAME_SIZE,
			       LEGA_MQ_HEARTBEAT,
			       &client_properties,
			       AMQP_SASL_METHOD_PLAIN,
			       "guest",
			       "guest"); // Note: configured as loopback user only!

  if (amqp_ret.reply_type != AMQP_RESPONSE_NORMAL) {
    D2("Error: Logging in");
    return 3;
  }

  amqp_channel_open(mq_conn, 1);
  amqp_ret = amqp_get_rpc_reply(mq_conn);
  if (amqp_ret.reply_type != AMQP_RESPONSE_NORMAL) {
    D2("Error opening channel");
    return 4;
  }

  /* Success: Mark it as opened */
  mq_conn_initialized = 1;
  return 0;
}

int
mq_clean(void)
{
  if(!mq_conn || !mq_conn_initialized) return 0;

  D2("Cleaning connection to message broker");
  amqp_rpc_reply_t amqp_ret;
  int rc;

  amqp_ret = amqp_channel_close(mq_conn, 1, AMQP_REPLY_SUCCESS);
  if (amqp_ret.reply_type != AMQP_RESPONSE_NORMAL) {
    D2("Error closing channel: %s", amqp_rpc_reply_string(amqp_ret));
    //return 1;
    goto clean;
  }

  amqp_ret = amqp_connection_close(mq_conn, AMQP_REPLY_SUCCESS);
  if (amqp_ret.reply_type != AMQP_RESPONSE_NORMAL) {
    D2("Error closing connection: %s", amqp_rpc_reply_string(amqp_ret));
    //return 2;
    goto clean;
  }

clean:
  if ((rc = amqp_destroy_connection(mq_conn)) < 0) { // closes socket too
    D2("Error: Ending connection");
    return 3;
  }

  mq_conn_initialized = 0;
  mq_conn = NULL;
  return 0;
}


/* ================================================
 *
 *                For the messages
 *
 * ================================================ */
static int
do_send_message(const char* message)
{
  /* Ensure connected */
  if(mq_init() != 0) return 1;

  amqp_basic_properties_t props;
  props._flags = AMQP_BASIC_CONTENT_TYPE_FLAG |
                 AMQP_BASIC_DELIVERY_MODE_FLAG |
                 AMQP_BASIC_CORRELATION_ID_FLAG | 
                 AMQP_BASIC_TIMESTAMP_FLAG |
                 AMQP_BASIC_HEADERS_FLAG;

  props.content_type = amqp_cstring_bytes("application/json");
  props.delivery_mode = 2; /* persistent delivery mode */

  props.headers = headers;

  /* Generate Correlation id */
  static char correlation_id[UUID_STR_LEN];
  uuid_t uu;
  uuid_generate(uu);
  uuid_unparse(uu, correlation_id);
  D3("Correlation ID: %s", correlation_id);
  props.correlation_id = amqp_cstring_bytes(correlation_id);

  props.timestamp = (u_int64_t)time(NULL);

  D3("sending to MQ: %s", message);

  /* We need to check if we have not previously received a ConnectionClosed message,
   * in which case, we'd have to reconnect, cuz the publish() wouldn't tell so.
   * For that, we check if there is a frame waiting, but we don't block.
   * If there is, it's a method frame and its payload is connection_closed, then we reconnect.
   * We also reconnect on error pulling the frame.
   * Note: We don't check the SO_ERROR on the socket, nor if there only are bytes waiting in it
   * See: https://github.com/alanxz/rabbitmq-c/issues/418
   */

  unsigned int maxtry = 2;
  amqp_frame_t decoded_frame;
  decoded_frame.frame_type = 0; /* will be flipped if we find a frame */
  struct timeval tv = { .tv_sec = 0, .tv_usec = 0}; /* implies non-block */
  int res = amqp_simple_wait_frame_noblock(mq_conn, &decoded_frame, &tv);
  if(res != AMQP_STATUS_OK && res != AMQP_STATUS_TIMEOUT){
    /* We got a frame, or there was an error: reconnect anyway */
    D1("Waiting for frame: %s", amqp_error_string2(res));
    goto reconnect;
  }

  /* If we timed-out, was there a frame and was it a connection-closed frame ?
   * Note: we don't put the frame back. We only care if it was a disconnection from the broker.
   */
  if(decoded_frame.frame_type == 0 /* ignored frame */
     || !(decoded_frame.frame_type == AMQP_FRAME_METHOD &&
	  decoded_frame.payload.method.id == AMQP_CONNECTION_CLOSE_METHOD) /* connection closed by broker */
     )
    goto send;

reconnect:
  if (!maxtry){
    D1("Max attempts exhausted");
    return 1;
  }

  D3("Reconnecting");
  if(mq_clean() || mq_init()){
    D1("Could not reconnect");
    return 2;
  }

send:
  res = amqp_basic_publish(mq_conn,
			   1, /* channel */
			   exchange,
			   routing_key,
			   0 /* mandatory */,
			   0 /* immediate */, /* Note: RabbitMQ doesn't implement "immediate" */
			   &props, 
			   amqp_cstring_bytes(message)); /* body */

  
  if(res == AMQP_STATUS_OK){
    return 0; /* all good */
  }
   
  /* retry */
  if(res == AMQP_STATUS_SOCKET_ERROR ||
     res == AMQP_STATUS_CONNECTION_CLOSED ||
     res == AMQP_STATUS_TCP_ERROR ||
     res == AMQP_STATUS_TIMER_FAILURE ||
     res == AMQP_STATUS_HEARTBEAT_TIMEOUT)
    {
      D1("Message not sent because: %s", amqp_error_string2(res));
      maxtry--;
      D3("Sending attempt left: %d", maxtry);
      goto reconnect;
    }

  /* otherwise */
  D1("Unable to send message: %s", amqp_error_string2(res));
  return 1;
}

static int
mq_send_upload(const char* username, const char* filepath, const char* hexdigest, const off_t filesize, const time_t modified)
{ 
  D2("%s uploaded %s", username, filepath);
  char* msg = NULL;
  int ret;
  json_object *obj = json_object_new_object();

  json_object_object_add(obj,
			 "user",
			 json_object_new_string(username));
  json_object_object_add(obj,
			 "filepath",
			 json_object_new_string(filepath));
  json_object_object_add(obj,
			 "operation",
			 json_object_new_string("upload"));
  /* Checksum */
  json_object *jchecksum = json_object_new_object();
  json_object_object_add(jchecksum, "type", json_object_new_string("sha256"));
  json_object_object_add(jchecksum, "value", json_object_new_string(hexdigest));
  json_object *jarray = json_object_new_array();
  json_object_array_add(jarray, jchecksum);
  json_object_object_add(obj,
			 "encrypted_checksums",
			 jarray);
  /* Filesize */
  json_object_object_add(obj,
			 "filesize",
			 json_object_new_int64(filesize));
  /* Timestamp last modified */
  json_object_object_add(obj,
			 "file_last_modified",
			 json_object_new_int64(modified));

  msg = json_object_to_json_string_ext(obj, JSON_C_TO_STRING_NOSLASHESCAPE);
  ret = do_send_message(msg);
  json_object_put(obj); // free json object, and the other ones inside
  return (ret) ? 2 : 0;
}

static int
mq_send_remove(const char* username, const char* filepath)
{ 
  D2("%s removed %s", username, filepath);
  char* msg = NULL;
  int ret;
  json_object *obj = json_object_new_object();

  json_object_object_add(obj,
			 "user",
			 json_object_new_string(username));
  json_object_object_add(obj,
			 "filepath",
			 json_object_new_string(filepath));
  json_object_object_add(obj,
			 "operation",
			 json_object_new_string("remove"));

  msg = json_object_to_json_string_ext(obj, JSON_C_TO_STRING_NOSLASHESCAPE);
  ret = do_send_message(msg);
  json_object_put(obj); // free json object, and the other ones inside
  return (ret) ? 2 : 0;
}

static int
mq_send_rename(const char* username, const char* oldpath, const char* newpath)
{ 
  D2("%s renamed %s into %s", username, oldpath, newpath);
  char* msg = NULL;
  int ret;
  json_object *obj = json_object_new_object();

  json_object_object_add(obj,
			 "user",
			 json_object_new_string(username));
  json_object_object_add(obj,
			 "filepath",
			 json_object_new_string(newpath));
  json_object_object_add(obj,
			 "operation",
			 json_object_new_string("rename"));
  json_object_object_add(obj,
			 "oldpath",
			 json_object_new_string(oldpath));

  msg = json_object_to_json_string_ext(obj, JSON_C_TO_STRING_NOSLASHESCAPE);
  ret = do_send_message(msg);
  json_object_put(obj); // free json object, and the other ones inside
  return (ret) ? 2 : 0;
}


/* ================================================
 *
 *                Utilities
 *
 * ================================================ */

static const char*
amqp_server_exception_string(amqp_rpc_reply_t r) {
  int res;
  static char s[512];

  switch (r.reply.id) {
    case AMQP_CONNECTION_CLOSE_METHOD: {
      amqp_connection_close_t *m = (amqp_connection_close_t *)r.reply.decoded;
      res = snprintf(s, sizeof(s), "server connection error %d, message: %.*s",
                     m->reply_code, (int)m->reply_text.len, (char *)m->reply_text.bytes);
      break;
    }

    case AMQP_CHANNEL_CLOSE_METHOD: {
      amqp_channel_close_t *m = (amqp_channel_close_t *)r.reply.decoded;
      res = snprintf(s, sizeof(s), "server channel error %d, message: %.*s",
                     m->reply_code, (int)m->reply_text.len, (char *)m->reply_text.bytes);
      break;
    }

    default:
      res = snprintf(s, sizeof(s), "unknown server error, method id 0x%08X", r.reply.id);
      break;
  }

  return res >= 0 ? s : NULL;
}

static const char*
amqp_rpc_reply_string(amqp_rpc_reply_t r) {
  switch (r.reply_type) {
  case AMQP_RESPONSE_NORMAL:
    return "normal response";
    
  case AMQP_RESPONSE_NONE:
    return "missing RPC reply type";
    
  case AMQP_RESPONSE_LIBRARY_EXCEPTION:
    return amqp_error_string2(r.library_error);
    
  case AMQP_RESPONSE_SERVER_EXCEPTION:
    return amqp_server_exception_string(r);
    
  default:
    abort();
  }
}
