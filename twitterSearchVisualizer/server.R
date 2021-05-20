library('shiny')
library('twitteR')
library('d3Network')
library('plyr')

origop <- options("httr_oauth_cache")
options(httr_oauth_cache=TRUE)
setup_twitter_oauth(consumer_key='REDACTED',
                    consumer_secret='REDACTED',
                    access_token='REDACTED',
                    access_secret='REDACTED')
options(httr_oauth_cache=origop)

function(input, output) {
  values <- reactiveValues()
  getPage<-function(searchterm) {
    tweets <- laply(rawresults, function(t) t$getText())
    tweeters <- laply(rawresults, function(t) t$getScreenName())
    #replies <- laply(rawresults, function(t) t$getReplyToSN())
    mentions <- data.frame(sender=character(),mention=character())
    for (i in 1:length(tweets)){
      split <- unlist(lapply(tweets[i], function(s) strsplit(s," ")))
      split <- split[grep('@',split)]
      #print(split)
      for (j in 1:length(split)) {
        if(!identical(split[j],character(0))){
          split[j] <- gsub("\n",'',split[j])
          split[j] <- gsub("(?!')[[:punct:]]", "", split[j], perl=TRUE)
          #print(split[j])
          mentions <- rbind(mentions,data.frame(tweeters[i],split[j]))
        }
      }
    }
    graphtext <- d3SimpleNetwork(mentions,standAlone=FALSE,parentElement='#inc')
    return(graphtext)
  }
  observe({
    if(input$RunModel==0){
      default <-"<!DOCTYPE html>
      <body> 
      Wait just a second!
</body>"
      output$inc<-renderUI(HTML(default))
    }
    else{
      output$terms<-renderUI(tags$h3(paste("Your search was for: ",input$search)))
      output$inc<-renderPrint({
        if(input$time=='Custom'){
          rawresults <- searchTwitter(as.character(input$search),n=100,
                                      since=as.character(input$start),until=as.character(input$end))
        }
        else{
          rawresults <- searchTwitter(as.character(input$search),n=100)
        }
        tweets <- laply(rawresults, function(t) t$getText())
        tweeters <- laply(rawresults, function(t) t$getScreenName())
        mentions <- data.frame(sender=character(),mention=character())
        for (i in 1:length(tweets)){
          split <- unlist(lapply(tweets[i], function(s) strsplit(s," ")))
          split <- split[grep('@',split)]
          for (j in 1:length(split)) {
            if(!identical(split[j],character(0))){
              split[j] <- tolower(split[j])
              split[j] <- gsub("\n",'',split[j])
              split[j] <- gsub("(?!')[[:punct:]]", "", split[j], perl=TRUE)
              #print(split[j])
              mentions <- rbind(mentions,data.frame(tweeters[i],split[j]))
            }
          }
        }
        d3SimpleNetwork(mentions[!is.na(mentions[,2]),],standAlone=FALSE,parentElement='#inc')
      })
    }
  })
}